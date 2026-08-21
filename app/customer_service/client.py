"""微信客服 (WeChat Customer Service) API client.

凭证体系与公众号完全独立：企业ID + 客服Secret，走 qyapi.weixin.qq.com。
"""

import asyncio
import json
import time
from pathlib import Path
from typing import Any

import httpx
from fastapi import HTTPException

from ..config import settings


class CustomerServiceClient:
    """Async 微信客服 client：token 缓存 + sync_msg 增量拉取 + 消息下发."""

    def __init__(
        self,
        *,
        corpid: str | None = None,
        secret: str | None = None,
        base_url: str | None = None,
        cursor_path: str | None = None,
    ) -> None:
        self._corpid = corpid if corpid is not None else settings.cs_corpid
        self._secret = secret if secret is not None else settings.cs_secret
        self._base_url = base_url or settings.cs_api_base
        self._http: httpx.AsyncClient | None = None
        self._token: str | None = None
        self._token_expiry: float = 0.0
        self._lock = asyncio.Lock()
        if cursor_path is None:
            cursor_path = settings.cs_cursor_path
        self._cursor_path: Path | None = Path(cursor_path) if cursor_path else None

    @property
    def _client(self) -> httpx.AsyncClient:
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(base_url=self._base_url, timeout=15.0)
        return self._http

    async def close(self) -> None:
        if self._http is not None and not self._http.is_closed:
            await self._http.aclose()

    # ---------------- token ----------------

    def _require_credentials(self) -> tuple[str, str]:
        if not self._corpid or not self._secret:
            raise HTTPException(500, "CS_CORPID / CS_SECRET not configured")
        return self._corpid, self._secret

    async def get_access_token(self) -> str:
        async with self._lock:
            if self._token and time.time() < self._token_expiry - 60:
                return self._token
            corpid, secret = self._require_credentials()
            resp = await self._client.get(
                "/cgi-bin/gettoken", params={"corpid": corpid, "corpsecret": secret}
            )
            data = resp.json()
            if data.get("errcode", 0) != 0 or "access_token" not in data:
                raise HTTPException(502, f"gettoken failed: {data}")
            self._token = data["access_token"]
            self._token_expiry = time.time() + float(data.get("expires_in", 7200))
            return self._token

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        token = await self.get_access_token()
        resp = await self._client.post(path, params={"access_token": token}, json=payload)
        return resp.json()

    # ---------------- cursor persistence ----------------

    def _load_cursor(self) -> str:
        if not self._cursor_path or not self._cursor_path.exists():
            return ""
        try:
            return json.loads(self._cursor_path.read_text()).get("cursor", "")
        except (OSError, json.JSONDecodeError):
            return ""

    def _save_cursor(self, cursor: str) -> None:
        if not self._cursor_path or not cursor:
            return
        try:
            self._cursor_path.write_text(json.dumps({"cursor": cursor}))
        except OSError:
            pass

    # ---------------- messaging ----------------

    async def sync_msg(
        self,
        *,
        token: str = "",
        open_kfid: str = "",
        voice_format: int = 0,
    ) -> list[dict[str, Any]]:
        """增量拉取消息，翻完所有页并持久化 next_cursor."""
        cursor = self._load_cursor()
        messages: list[dict[str, Any]] = []
        while True:
            payload: dict[str, Any] = {"voice_format": voice_format}
            if cursor:
                payload["cursor"] = cursor
            if token:
                payload["token"] = token
            if open_kfid:
                payload["open_kfid"] = open_kfid
            data = await self._post("/cgi-bin/kf/sync_msg", payload)
            if data.get("errcode", 0) != 0:
                raise HTTPException(502, f"sync_msg failed: {data}")
            messages.extend(data.get("msg_list", []))
            cursor = data.get("next_cursor", cursor)
            self._save_cursor(cursor)
            if not data.get("has_more"):
                return messages

    async def upload_media(
        self, data: bytes, *, filename: str, media_type: str = "image"
    ) -> str:
        """上传临时素材，返回 media_id。素材 3 天后失效.

        media_type: image | voice | video | file
        """
        token = await self.get_access_token()
        resp = await self._client.post(
            "/cgi-bin/media/upload",
            params={"access_token": token, "type": media_type},
            files={"media": (filename, data)},
        )
        payload = resp.json()
        if payload.get("errcode", 0) != 0 or "media_id" not in payload:
            raise HTTPException(502, f"media/upload failed: {payload}")
        return payload["media_id"]

    async def send_image(self, *, touser: str, open_kfid: str, media_id: str) -> dict[str, Any]:
        return await self.send_msg(
            {
                "touser": touser,
                "open_kfid": open_kfid,
                "msgtype": "image",
                "image": {"media_id": media_id},
            }
        )

    async def get_customers(
        self, external_userids: list[str], *, need_enter_session_context: int = 1
    ) -> list[dict[str, Any]]:
        """获取客户基础信息。仅对 48 小时内有过互动的客户有效.

        unionid 需企业绑定同主体的公众号/小程序后才会下发，否则为 None。
        """
        data = await self._post(
            "/cgi-bin/kf/customer/batchget",
            {
                "external_userid_list": external_userids,
                "need_enter_session_context": need_enter_session_context,
            },
        )
        if data.get("errcode", 0) != 0:
            raise HTTPException(502, f"customer/batchget failed: {data}")
        return data.get("customer_list", [])

    async def get_media(self, media_id: str) -> tuple[bytes, str]:
        """下载临时素材，返回 (二进制内容, content_type)。素材仅保留 3 天."""
        token = await self.get_access_token()
        resp = await self._client.get(
            "/cgi-bin/media/get", params={"access_token": token, "media_id": media_id}
        )
        content_type = resp.headers.get("content-type", "")
        # 出错时微信返回 JSON 而非二进制流
        if content_type.startswith("application/json"):
            raise HTTPException(502, f"media/get failed: {resp.json()}")
        return resp.content, content_type

    async def send_msg(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._post("/cgi-bin/kf/send_msg", payload)

    async def send_text(self, *, touser: str, open_kfid: str, content: str) -> dict[str, Any]:
        return await self.send_msg(
            {
                "touser": touser,
                "open_kfid": open_kfid,
                "msgtype": "text",
                "text": {"content": content},
            }
        )

    async def send_welcome(self, *, code: str, content: str) -> dict[str, Any]:
        """用 enter_session 事件返回的 welcome_code 发送欢迎语."""
        return await self._post(
            "/cgi-bin/kf/send_msg_on_event",
            {"code": code, "msgtype": "text", "text": {"content": content}},
        )


customer_service_client = CustomerServiceClient()
