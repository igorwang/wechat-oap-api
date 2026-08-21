"""客服机器人编排：回调事件 → sync_msg 拉取 → DeepSeek 生成回复 → send_msg 下发."""

import logging
from typing import Any

import httpx

from ..config import settings
from .client import CustomerServiceClient, customer_service_client

logger = logging.getLogger(__name__)


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
    ) -> None:
        self._client = client
        self._api_key = api_key if api_key is not None else settings.deepseek_api_key
        self._api_base = api_base or settings.deepseek_api_base
        self._model = model or settings.deepseek_model
        self._system_prompt = (
            system_prompt if system_prompt is not None else settings.deepseek_system_prompt
        )
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

    async def _handle(self, msg: dict[str, Any]) -> bool:
        msgtype = msg.get("msgtype")
        if msgtype == "event":
            event = msg.get("event", {})
            code = event.get("welcome_code")
            if event.get("event_type") == "enter_session" and code:
                await self._client.send_welcome(code=code, content=self._welcome_text)
                return True
            return False
        # 3 = 客户发送的消息
        if msg.get("origin") != 3 or msgtype != "text":
            return False
        answer = await self.reply(msg["text"]["content"])
        await self._client.send_text(
            touser=msg["external_userid"], open_kfid=msg["open_kfid"], content=answer
        )
        return True

    async def process_event(self, *, token: str = "", open_kfid: str = "") -> int:
        """处理一次 kf_msg_or_event 回调：拉取新消息并逐条响应，返回已处理条数."""
        messages = await self._client.sync_msg(token=token, open_kfid=open_kfid)
        handled = 0
        for msg in messages:
            try:
                if await self._handle(msg):
                    handled += 1
            except Exception:
                logger.exception("failed to handle message %s", msg.get("msgid"))
        return handled


support_bot = SupportBot(customer_service_client)
