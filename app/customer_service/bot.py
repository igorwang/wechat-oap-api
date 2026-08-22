"""客服机器人编排：回调事件 → sync_msg 拉取 → DeepSeek 生成回复 → send_msg 下发."""

import logging
import time
from pathlib import Path
from typing import Any

import httpx

from ..config import settings
from ..followers import FollowerDirectory, follower_directory
from .client import CustomerServiceClient, customer_service_client
from .perception import Perception
from .prompts import (
    FOLLOW_PROMPT,
    IMAGE_CONTEXT_TEMPLATE,
    MEDIA_FALLBACK_TEXT,
    SYSTEM_PROMPT,
)
from .store import CustomerStore

logger = logging.getLogger(__name__)

_QR_PATH = Path(__file__).resolve().parent.parent / "static" / "qrcode-official-account.jpg"
# 微信临时素材 3 天失效，留一天余量
_QR_MEDIA_TTL = 2 * 24 * 3600
# 客户发来的、会被接待的消息类型；其余（视频/文件/位置/名片…）暂不处理
_SUPPORTED_MSGTYPES = ("text", "voice", "image")
# 百炼单个媒体上限 10MB。微信语音最长 60 秒（AMR 约 90KB），只有图片可能撞线
_MAX_MEDIA_BYTES = 10 * 1024 * 1024
_IMAGE_MAGIC = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF8", "image/gif"),
)


def _image_mime(data: bytes, content_type: str) -> str:
    """认出图片真实类型.

    微信 media/get 有时回 application/octet-stream，而百炼只认 png/jpeg/webp，
    标错会被拒，所以 header 不可信时自己看字节头。
    """
    kind = content_type.split(";")[0].strip().lower()
    if kind.startswith("image/"):
        return kind
    for magic, mime in _IMAGE_MAGIC:
        if data.startswith(magic):
            return mime
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


class SupportBot:
    def __init__(
        self,
        client: CustomerServiceClient,
        *,
        api_key: str | None = None,
        api_base: str | None = None,
        model: str | None = None,
        system_prompt: str | None = None,
        welcome_text: str | None = None,
        store: "CustomerStore | None" = None,
        require_follow: bool | None = None,
        followers: "FollowerDirectory | None" = None,
        perception: "Perception | None" = None,
    ) -> None:
        self._client = client
        self.store = store
        self._perception = perception or Perception()
        self._require_follow = (
            require_follow if require_follow is not None else settings.cs_require_follow
        )
        self._followers = followers or follower_directory
        self._qr_media_id: str | None = None
        self._qr_media_at = 0.0
        self._api_key = api_key if api_key is not None else settings.deepseek_api_key
        self._api_base = api_base or settings.deepseek_api_base
        self._model = model or settings.deepseek_model
        self._system_prompt = system_prompt if system_prompt is not None else SYSTEM_PROMPT
        self._welcome_text = (
            welcome_text if welcome_text is not None else settings.cs_welcome_text
        )

    async def reply(self, text: str) -> str:
        """调 DeepSeek chat/completions 生成回复文本."""
        async with httpx.AsyncClient(base_url=self._api_base, timeout=60.0) as http:
            resp = await http.post(
                "/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "model": self._model,
                    "messages": [
                        {"role": "system", "content": self._system_prompt},
                        {"role": "user", "content": text},
                    ],
                },
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]

    async def _record(
        self,
        external_userid: str,
        *,
        open_kfid: str = "",
        scene: str = "",
        scene_param: str = "",
        fetch_profile: bool = False,
        bump_message_count: bool = False,
    ) -> None:
        """把客户信息落库。external_userid 仅在 48h 内可查，必须当场记录."""
        if not self.store or not external_userid:
            return
        profile: dict[str, Any] = {"external_userid": external_userid}
        if fetch_profile:
            try:
                data = await self._client.get_customers([external_userid])
                if data:
                    profile = data[0]
            except Exception:
                logger.exception("failed to fetch profile for %s", external_userid)
        try:
            await self.store.upsert(
                profile,
                open_kfid=open_kfid or None,
                scene=scene or None,
                scene_param=scene_param or None,
                bump_message_count=bump_message_count,
            )
        except Exception:
            logger.exception("failed to persist customer %s", external_userid)

    async def _is_follower(self, external_userid: str, *, open_kfid: str = "") -> bool:
        """客户当前是否关注了公众号.

        unionid 只是把客服侧的客户和公众号侧的用户对上号——它本身判断不了关注
        状态（会话本身就会分配 unionid，取关也不回收），真正的判据是这个 unionid
        在不在公众号关注者名单里。
        """
        unionid = await self._lookup_unionid(external_userid, open_kfid=open_kfid)
        if not unionid:
            return False
        try:
            followed = await self._followers.is_follower(unionid)
            logger.info("关注状态 unionid=%s followed=%s", unionid, followed)
            return followed
        except Exception:
            # 拉不到关注名单时按未关注拦下——放行会让门禁静默失效，比误拦难发现
            logger.exception("failed to check follower status for %s", external_userid)
            return False

    async def _lookup_unionid(self, external_userid: str, *, open_kfid: str = "") -> str | None:
        """取客户 unionid：先读库，未命中再打接口并顺手落库."""
        if self.store:
            try:
                row = await self.store.get(external_userid)
                if row and row.unionid:
                    return row.unionid
            except Exception:
                logger.exception("failed to read customer %s", external_userid)
        try:
            found = await self._client.get_customers([external_userid])
        except Exception:
            logger.exception("failed to fetch profile for %s", external_userid)
            return None
        if not found:
            logger.warning("customer/batchget returned nothing for %s", external_userid)
            return None
        profile = found[0]
        if self.store:
            try:
                await self.store.upsert(profile, open_kfid=open_kfid or None)
            except Exception:
                logger.exception("failed to persist customer %s", external_userid)
        return profile.get("unionid") or None

    async def _qr_media_id_cached(self) -> str | None:
        now = time.monotonic()
        if self._qr_media_id and now - self._qr_media_at < _QR_MEDIA_TTL:
            return self._qr_media_id
        try:
            data = _QR_PATH.read_bytes()
        except OSError:
            logger.exception("公众号二维码缺失: %s", _QR_PATH)
            return None
        self._qr_media_id = await self._client.upload_media(data, filename=_QR_PATH.name)
        self._qr_media_at = now
        return self._qr_media_id

    async def _send_follow_prompt(self, *, touser: str, open_kfid: str) -> None:
        await self._client.send_text(touser=touser, open_kfid=open_kfid, content=FOLLOW_PROMPT)
        media_id = await self._qr_media_id_cached()
        if media_id:
            await self._client.send_image(touser=touser, open_kfid=open_kfid, media_id=media_id)

    async def _handle(self, msg: dict[str, Any]) -> bool:
        msgtype = msg.get("msgtype")
        if msgtype == "event":
            event = msg.get("event", {})
            if event.get("event_type") == "enter_session":
                await self._record(
                    event.get("external_userid", ""),
                    open_kfid=event.get("open_kfid", ""),
                    scene=event.get("scene", ""),
                    scene_param=event.get("scene_param", ""),
                    fetch_profile=True,
                )
            code = event.get("welcome_code")
            if event.get("event_type") == "enter_session" and code:
                logger.info(
                    "👋 进入会话 from=%s scene=%r，发送欢迎语",
                    event.get("external_userid"), event.get("scene", ""),
                )
                await self._client.send_welcome(code=code, content=self._welcome_text)
                return True
            return False
        # 3 = 客户发送的消息
        if msg.get("origin") != 3 or msgtype not in _SUPPORTED_MSGTYPES:
            logger.info(
                "跳过消息 msgid=%s origin=%s type=%s（只接待客户发来的文字/语音/图片）",
                msg.get("msgid"), msg.get("origin"), msgtype,
            )
            return False
        external_userid = msg["external_userid"]
        open_kfid = msg["open_kfid"]
        await self._record(
            external_userid, open_kfid=open_kfid, bump_message_count=True
        )
        # 门禁必须在识别之前：未关注的客户不该花掉一次 ASR/视觉调用
        if self._require_follow and not await self._is_follower(
            external_userid, open_kfid=open_kfid
        ):
            logger.info("🚧 门禁拦下（未关注公众号）from=%s，发送引导二维码", external_userid)
            await self._send_follow_prompt(touser=external_userid, open_kfid=open_kfid)
            return True
        content = await self._to_text(msg, external_userid=external_userid)
        if not content:
            # 识别不出内容也要出声，否则客户对着空气等
            await self._client.send_text(
                touser=external_userid, open_kfid=open_kfid, content=MEDIA_FALLBACK_TEXT
            )
            return True
        answer = await self.reply(content)
        logger.info("🤖 已回复 to=%s content=%r", external_userid, answer[:100])
        await self._client.send_text(
            touser=external_userid, open_kfid=open_kfid, content=answer
        )
        return True

    async def _to_text(self, msg: dict[str, Any], *, external_userid: str) -> str:
        """把客户发来的消息变成一段交给大脑的文本；识别不出来返回空串.

        语音转写后原样当成客户说的话；图片先让视觉模型客观描述，再包一层转述，
        因为 DeepSeek 看不见图，得知道这段文字是图片内容而不是客户的原话。
        """
        msgtype = msg["msgtype"]
        if msgtype == "text":
            content = msg["text"]["content"]
            logger.info("💬 收到消息 from=%s content=%r", external_userid, content[:100])
            return content

        is_voice = msgtype == "voice"
        kind = "语音" if is_voice else "图片"
        media_id = (msg.get(msgtype) or {}).get("media_id", "")
        logger.info(
            "%s 收到%s from=%s media_id=%s", "🎤" if is_voice else "🖼️",
            kind, external_userid, media_id,
        )
        if not media_id:
            logger.warning("%s消息没有 media_id msgid=%s", kind, msg.get("msgid"))
            return ""
        try:
            data, content_type = await self._client.get_media(media_id)
        except Exception:
            logger.exception("下载%s失败 media_id=%s", kind, media_id)
            return ""
        if len(data) > _MAX_MEDIA_BYTES:
            logger.warning(
                "%s %d 字节，超过百炼 %dMB 上限，不送模型",
                kind, len(data), _MAX_MEDIA_BYTES // 1024 // 1024,
            )
            return ""
        try:
            if is_voice:
                # sync_msg 用 voice_format=0 拉的就是 AMR，百炼直接能读，无需转码
                text = (await self._perception.transcribe(data, mime="audio/amr")).strip()
                logger.info("📝 语音转写 from=%s text=%r", external_userid, text[:100])
                return text
            described = (
                await self._perception.describe_image(
                    data, mime=_image_mime(data, content_type)
                )
            ).strip()
            logger.info("👁️ 图片识别 from=%s desc=%r", external_userid, described[:150])
            return IMAGE_CONTEXT_TEMPLATE.format(description=described) if described else ""
        except Exception:
            logger.exception("%s识别失败 media_id=%s", kind, media_id)
            return ""

    async def process_event(self, *, token: str = "", open_kfid: str = "") -> int:
        """处理一次 kf_msg_or_event 回调：拉取新消息并逐条响应，返回已处理条数.

        跑在 BackgroundTask 里，响应此时已发出，抛异常只会变成一句无用的
        "response already started" —— 所以这里必须自己消化掉所有错误。
        """
        try:
            messages = await self._client.sync_msg(token=token, open_kfid=open_kfid)
        except Exception:
            logger.exception("sync_msg failed (open_kfid=%s)", open_kfid)
            return 0
        if messages:
            logger.info("拉取到 %d 条新消息 open_kfid=%s", len(messages), open_kfid)
        handled = 0
        for msg in messages:
            try:
                if await self._handle(msg):
                    handled += 1
            except Exception:
                logger.exception("failed to handle message %s", msg.get("msgid"))
        return handled


support_bot = SupportBot(customer_service_client)
