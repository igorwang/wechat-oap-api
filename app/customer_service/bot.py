"""客服机器人编排：回调事件 → sync_msg 拉取 → DeepSeek 生成回复 → send_msg 下发."""

import logging
import time
from pathlib import Path
from typing import Any

import httpx

from ..config import settings
from ..followers import FollowerDirectory, follower_directory
from .client import CustomerServiceClient, customer_service_client
from .prompts import FOLLOW_PROMPT, SYSTEM_PROMPT
from .store import CustomerStore

logger = logging.getLogger(__name__)

_QR_PATH = Path(__file__).resolve().parent.parent / "static" / "qrcode-official-account.jpg"
# 微信临时素材 3 天失效，留一天余量
_QR_MEDIA_TTL = 2 * 24 * 3600


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
    ) -> None:
        self._client = client
        self.store = store
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
        if msg.get("origin") != 3 or msgtype != "text":
            logger.info(
                "跳过消息 msgid=%s origin=%s type=%s（只处理客户发来的文本）",
                msg.get("msgid"), msg.get("origin"), msgtype,
            )
            return False
        external_userid = msg["external_userid"]
        content = msg["text"]["content"]
        logger.info("💬 收到消息 from=%s content=%r", external_userid, content[:100])
        await self._record(
            msg.get("external_userid", ""),
            open_kfid=msg.get("open_kfid", ""),
            bump_message_count=True,
        )
        if self._require_follow and not await self._is_follower(
            external_userid, open_kfid=msg["open_kfid"]
        ):
            logger.info("🚧 门禁拦下（未关注公众号）from=%s，发送引导二维码", external_userid)
            await self._send_follow_prompt(
                touser=external_userid, open_kfid=msg["open_kfid"]
            )
            return True
        answer = await self.reply(content)
        logger.info("🤖 已回复 to=%s content=%r", external_userid, answer[:100])
        await self._client.send_text(
            touser=external_userid, open_kfid=msg["open_kfid"], content=answer
        )
        return True

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
