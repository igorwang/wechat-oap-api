import asyncio
import json
import time
from pathlib import Path
from typing import Any

import httpx
from fastapi import HTTPException

from .config import settings


class WeChatClient:
    """Async WeChat 服务端 API client with token caching.

    Caching strategy:
    * in-process `_token` + `_token_expiry` (60s safety margin)
    * optional file persistence at `settings.wechat_token_cache_path`
    * `asyncio.Lock` to dedupe concurrent refreshes
    * transparent retry once on 40001 / 42001
    """

    def __init__(self, *, cache_path: str | None = None) -> None:
        self._http: httpx.AsyncClient | None = None
        self._token: str | None = None
        self._token_expiry: float = 0.0
        self._lock = asyncio.Lock()
        if cache_path is None:
            cache_path = settings.wechat_token_cache_path
        self._cache_path: Path | None = Path(cache_path) if cache_path else None
        self._load_cached_token()

    @property
    def _client(self) -> httpx.AsyncClient:
        """Lazily (re)create the underlying AsyncClient so lifespan close is safe."""
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(
                base_url=settings.wechat_api_base, timeout=15.0
            )
        return self._http

    async def close(self) -> None:
        if self._http is not None and not self._http.is_closed:
            await self._http.aclose()

    # ---------------- credentials / cache persistence ----------------

    def _require_app_credentials(self) -> tuple[str, str]:
        if not settings.wechat_appid or not settings.wechat_appsecret:
            raise HTTPException(500, "WECHAT_APPID / WECHAT_APPSECRET not configured")
        return settings.wechat_appid, settings.wechat_appsecret

    def _load_cached_token(self) -> None:
        if not self._cache_path or not self._cache_path.exists():
            return
        try:
            data = json.loads(self._cache_path.read_text())
        except (OSError, json.JSONDecodeError):
            return
        if data.get("appid") != settings.wechat_appid:
            return  # credentials changed, ignore stale cache
        token = data.get("access_token")
        expiry = float(data.get("expiry", 0))
        if token and time.time() < expiry - 60:
            self._token = token
            self._token_expiry = expiry

    def _save_cached_token(self) -> None:
        if not self._cache_path or not self._token:
            return
        payload = {
            "appid": settings.wechat_appid,
            "access_token": self._token,
            "expiry": self._token_expiry,
        }
        try:
            self._cache_path.write_text(json.dumps(payload))
        except OSError:
            pass

    # ---------------- token endpoints ----------------

    async def fetch_access_token(self, force_refresh: bool = False) -> dict[str, Any]:
        appid, secret = self._require_app_credentials()
        params = {"grant_type": "client_credential", "appid": appid, "secret": secret}
        if force_refresh:
            params["force_refresh"] = "true"
        r = await self._client.get("/cgi-bin/token", params=params)
        return r.json()

    async def fetch_stable_token(self, force_refresh: bool = False) -> dict[str, Any]:
        appid, secret = self._require_app_credentials()
        body = {
            "grant_type": "client_credential",
            "appid": appid,
            "secret": secret,
            "force_refresh": force_refresh,
        }
        r = await self._client.post("/cgi-bin/stable_token", json=body)
        return r.json()

    async def get_cached_access_token(self) -> str:
        now = time.time()
        if self._token and now < self._token_expiry - 60:
            return self._token
        async with self._lock:
            now = time.time()
            if self._token and now < self._token_expiry - 60:
                return self._token
            data = await self.fetch_access_token()
            if "access_token" not in data:
                raise HTTPException(502, f"WeChat token error: {data}")
            self._token = data["access_token"]
            self._token_expiry = now + int(data.get("expires_in", 7200))
            self._save_cached_token()
            return self._token

    def _invalidate_token(self) -> None:
        self._token = None
        self._token_expiry = 0.0
        if self._cache_path and self._cache_path.exists():
            try:
                self._cache_path.unlink()
            except OSError:
                pass

    # ---------------- generic helpers ----------------

    async def call_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """JSON-based authenticated call with auto token refresh on 40001/42001."""
        data: dict[str, Any] = {}
        for attempt in range(2):
            token = await self.get_cached_access_token()
            q = {"access_token": token, **(params or {})}
            r = await self._client.request(method, path, params=q, json=json)
            data = r.json()
            if data.get("errcode") in (40001, 42001) and attempt == 0:
                self._invalidate_token()
                continue
            return data
        return data

    async def call_multipart(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """multipart/form-data authenticated call (for file uploads)."""
        resp: dict[str, Any] = {}
        for attempt in range(2):
            token = await self.get_cached_access_token()
            q = {"access_token": token, **(params or {})}
            r = await self._client.request(method, path, params=q, data=data, files=files)
            resp = r.json()
            if resp.get("errcode") in (40001, 42001) and attempt == 0:
                self._invalidate_token()
                continue
            return resp
        return resp

    # ---------------- basic endpoints ----------------

    async def callback_check(
        self, action: str = "all", check_operator: str = "DEFAULT"
    ) -> dict[str, Any]:
        return await self.call_json(
            "POST",
            "/cgi-bin/callback/check",
            json={"action": action, "check_operator": check_operator},
        )

    async def get_api_domain_ip(self) -> dict[str, Any]:
        return await self.call_json("GET", "/cgi-bin/get_api_domain_ip")

    async def get_callback_ip(self) -> dict[str, Any]:
        return await self.call_json("GET", "/cgi-bin/getcallbackip")

    async def clear_quota(self, appid: str | None = None) -> dict[str, Any]:
        target_appid = appid or settings.wechat_appid
        if not target_appid:
            raise HTTPException(500, "appid required")
        return await self.call_json(
            "POST", "/cgi-bin/clear_quota", json={"appid": target_appid}
        )


wechat_client = WeChatClient()
