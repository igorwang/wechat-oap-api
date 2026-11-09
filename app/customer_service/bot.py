"""客服机器人编排：回调事件 → sync_msg 拉取 → DeepSeek 生成回复 → send_msg 下发."""

import asyncio
import logging
import time
from collections import deque
from pathlib import Path
from typing import Any

import httpx
from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError

from ..config import settings
from ..followers import FollowerDirectory, follower_directory
from .client import CustomerServiceClient, customer_service_client
from .perception import Perception
from .prompts import (
    FEYN_FAQ,
    FEYN_KNOWLEDGE,
    FEYN_PRODUCT_INTRO,
    FOLLOW_PROMPT,
    IMAGE_CONTEXT_TEMPLATE,
    MEDIA_FALLBACK_TEXT,
    SYSTEM_PROMPT,
    UNSUPPORTED_MEDIA_TEXT,
    normalize_feyn_question,
)
from .quota import CustomerQuotaStore
from .store import CustomerStore

logger = logging.getLogger(__name__)

_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
_QR_PATH = _STATIC_DIR / "qrcode-official-account.jpg"
# 群码默认用随镜像发布的那张（与公众号文章同一张）；CS_GROUP_QR_PATH 可覆盖
_DEFAULT_GROUP_QR_PATH = _STATIC_DIR / "feyn-group-qrcode.png"
# 微信临时素材 3 天失效，留一天余量
_QR_MEDIA_TTL = 2 * 24 * 3600
_JOIN_GROUP_KEYWORDS = {"进群", "加群", "加入群聊"}
_PRODUCT_KEYWORDS = {
    normalize_feyn_question(question)
    for question in ("产品", "产品介绍", "介绍产品", "介绍一下产品", "Feyn OS", "Feyn OS 是什么")
}
_DAILY_CHAT_LIMIT = 50
# 客户发来的、会被接待的消息类型；其余（视频/文件/位置/名片…）只回一句说明
_SUPPORTED_MSGTYPES = ("text", "voice", "image")
# 记住最近处理过的 msgid 用于判重。一次 sync 最多几十条，两千条足够覆盖
# 回调重推的时间窗；再多就是历史了，那时 cursor 早已推进
_DEDUP_CAPACITY = 2000
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
        quota: CustomerQuotaStore | None = None,
    ) -> None:
        self._client = client
        self.store = store
        self.quota = quota
        self._perception = perception or Perception()
        # 回调重推 + 每次回调都从 cursor 重新 sync = 同一条消息会被投递多次
        self._seen_msgids: set[str] = set()
        self._seen_order: deque[str] = deque()
        # 串行化整个「拉取 + 处理」，否则并发的两次回调会读到同一个 cursor
        self._event_lock = asyncio.Lock()
        self._require_follow = (
            require_follow if require_follow is not None else settings.cs_require_follow
        )
        self._followers = followers or follower_directory
        self._qr_media_cache: dict[Path, tuple[tuple[int, int], float, str]] = {}
        group_qr_path = settings.cs_group_qr_path.strip()
        self._group_qr_path = Path(group_qr_path) if group_qr_path else _DEFAULT_GROUP_QR_PATH
        self._api_key = api_key if api_key is not None else settings.deepseek_api_key
        self._api_base = api_base or settings.deepseek_api_base
        self._model = model or settings.deepseek_model
        self._system_prompt = system_prompt if system_prompt is not None else SYSTEM_PROMPT
        self._welcome_text = (
            welcome_text if welcome_text is not None else settings.cs_welcome_text
        )

    async def reply(self, text: str) -> str:
        """调 DeepSeek chat/completions 生成回复文本."""
        system_prompt = f"{self._system_prompt}\n以下是 Feyn OS 可对外回答的知识库。\n\n{FEYN_KNOWLEDGE}"
        async with httpx.AsyncClient(base_url=self._api_base, timeout=60.0) as http:
            resp = await http.post(
                "/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "model": self._model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
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

    async def _qr_media_id_cached(self, path: Path) -> str | None:
        now = time.monotonic()
        try:
            file = path.stat()
            version = (file.st_ino, file.st_mtime_ns)
            cached = self._qr_media_cache.get(path)
            if cached:
                cached_version, uploaded_at, media_id = cached
                if version == cached_version and now - uploaded_at < _QR_MEDIA_TTL:
                    return media_id
            data = path.read_bytes()
        except OSError:
            logger.exception("无法读取二维码图片: %s", path)
            return None
        media_id = await self._client.upload_media(data, filename=path.name)
        self._qr_media_cache[path] = (version, now, media_id)
        return media_id

    async def _send_follow_prompt(self, *, touser: str, open_kfid: str) -> None:
        await self._client.send_text(touser=touser, open_kfid=open_kfid, content=FOLLOW_PROMPT)
        media_id = await self._qr_media_id_cached(_QR_PATH)
        if media_id:
            await self._client.send_image(touser=touser, open_kfid=open_kfid, media_id=media_id)

    async def _send_group_invitation(self, path: Path, *, touser: str, open_kfid: str) -> None:
        reply = "暂时无法发送群二维码，请稍后再回复「进群」试试。"
        try:
            media_id = await self._qr_media_id_cached(path)
            if media_id:
                result = await self._client.send_image(
                    touser=touser, open_kfid=open_kfid, media_id=media_id
                )
                error_code = result.get("errcode")
                if error_code == 0:
                    reply = "收到群二维码后，长按识别即可申请加入交流群。"
                else:
                    if error_code == 40007:
                        self._qr_media_cache.pop(path, None)
                    logger.warning("发送群二维码失败，微信错误码: %s", error_code)
        except (HTTPException, httpx.HTTPError, ValueError):
            logger.exception("上传或发送群二维码失败")
        await self._client.send_text(touser=touser, open_kfid=open_kfid, content=reply)

    def _is_duplicate(self, msgid: str) -> bool:
        """这条 msgid 是否已经处理过；顺手记下.

        标记发生在派发时而不是完成后——和 cursor 一样是「取出即消费」：处理到
        一半失败就算了，也不要因为重试把客户的消息回两遍。
        没有 msgid 的消息无法判重，一律放行，宁可多回一次也不能漏。
        """
        if not msgid:
            return False
        if msgid in self._seen_msgids:
            return True
        self._seen_msgids.add(msgid)
        self._seen_order.append(msgid)
        while len(self._seen_order) > _DEDUP_CAPACITY:
            self._seen_msgids.discard(self._seen_order.popleft())
        return False

    async def _handle(self, msg: dict[str, Any]) -> bool:
        if self._is_duplicate(msg.get("msgid", "")):
            logger.info("↩️ 跳过重复投递 msgid=%s", msg.get("msgid"))
            return False
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
        # 3 = 客户发来的消息；其余是系统事件或客服自己发的，回它就成了自问自答
        if msg.get("origin") != 3:
            logger.info(
                "跳过消息 msgid=%s origin=%s type=%s（不是客户发来的）",
                msg.get("msgid"), msg.get("origin"), msgtype,
            )
            return False
        external_userid = msg["external_userid"]
        open_kfid = msg["open_kfid"]
        await self._record(
            external_userid, open_kfid=open_kfid, bump_message_count=True
        )
        if msgtype == "text":
            content = normalize_feyn_question(msg.get("text", {}).get("content", ""))
            fixed_reply = FEYN_PRODUCT_INTRO if content in _PRODUCT_KEYWORDS else FEYN_FAQ.get(content)
            if fixed_reply:
                await self._client.send_text(
                    touser=external_userid, open_kfid=open_kfid, content=fixed_reply
                )
                return True
            if content in _JOIN_GROUP_KEYWORDS:
                await self._send_group_invitation(
                    self._group_qr_path, touser=external_userid, open_kfid=open_kfid
                )
                return True
        # 门禁必须在识别之前：未关注的客户不该花掉一次 ASR/视觉调用
        if self._require_follow and not await self._is_follower(
            external_userid, open_kfid=open_kfid
        ):
            logger.info("🚧 门禁拦下（未关注公众号）from=%s，发送引导二维码", external_userid)
            await self._send_follow_prompt(touser=external_userid, open_kfid=open_kfid)
            return True
        if msgtype not in _SUPPORTED_MSGTYPES:
            logger.info(
                "📎 接不住的类型 msgid=%s type=%s from=%s，告知支持范围",
                msg.get("msgid"), msgtype, external_userid,
            )
            await self._client.send_text(
                touser=external_userid, open_kfid=open_kfid, content=UNSUPPORTED_MEDIA_TEXT
            )
            return True
        try:
            allowed = (
                await self.quota.try_consume(external_userid, limit=_DAILY_CHAT_LIMIT)
                if self.quota
                else None
            )
        except SQLAlchemyError as exc:
            logger.warning("客服额度暂不可用: %s", type(exc).__name__)
            allowed = None
        if allowed is not True:
            reply = (
                "AI 问答暂时不可用，请稍后再试。"
                if allowed is None
                else f"今天的 {_DAILY_CHAT_LIMIT} 条 AI 问答已用完。额度在北京时间零点重置。"
            )
            await self._client.send_text(touser=external_userid, open_kfid=open_kfid, content=reply)
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

        整段串行执行：微信 5 秒收不到响应就重推回调，而每次回调都从存下的
        cursor 重新拉取，并发跑会让两次拉取读到同一个 cursor、拿到同一批消息。
        """
        async with self._event_lock:
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
