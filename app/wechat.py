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
    * stable-token credentials, with a 60s expiry safety margin
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
        if not isinstance(data, dict):
            return
        if (
            data.get("appid") != settings.wechat_appid
            or data.get("token_source") != "stable_token"
        ):
            return  # Ignore another account's cache and pre-migration legacy tokens.
        token = data.get("access_token")
        try:
            expiry = float(data.get("expiry", 0))
        except (TypeError, ValueError):
            return
        if isinstance(token, str) and token and time.time() < expiry - 60:
            self._token = token
            self._token_expiry = expiry

    def _save_cached_token(self) -> None:
        if not self._cache_path or not self._token:
            return
        payload = {
            "appid": settings.wechat_appid,
            "token_source": "stable_token",
            "access_token": self._token,
            "expiry": self._token_expiry,
        }
        try:
            self._cache_path.write_text(json.dumps(payload))
        except OSError:
            pass

    def _cache_stable_token(self, data: dict[str, Any]) -> str:
        token = data.get("access_token")
        if not isinstance(token, str) or not token:
            raise HTTPException(
                502,
                detail={
                    "errcode": data.get("errcode"),
                    "errmsg": data.get("errmsg", "Invalid WeChat token response"),
                },
            )
        try:
            ttl = int(data["expires_in"])
        except (KeyError, TypeError, ValueError):
            raise HTTPException(502, "Invalid WeChat token expiry") from None
        if ttl <= 0:
            raise HTTPException(502, "Invalid WeChat token expiry")
        self._token = token
        self._token_expiry = time.time() + ttl
        self._save_cached_token()
        return token

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

    async def get_stable_token(self, force_refresh: bool = False) -> dict[str, Any]:
        """Explicit token requests also update the business cache under its lock."""
        async with self._lock:
            if force_refresh:
                self._invalidate_token()
            data = await self.fetch_stable_token(force_refresh=force_refresh)
            if "access_token" in data:
                self._cache_stable_token(data)
            return data

    async def get_cached_access_token(self, *, rejected_token: str | None = None) -> str:
        now = time.time()
        if rejected_token is None and self._token and now < self._token_expiry - 60:
            return self._token
        async with self._lock:
            now = time.time()
            if (
                self._token
                and now < self._token_expiry - 60
                and self._token != rejected_token
            ):
                return self._token
            # A late failure for OLD must not invalidate NEW refreshed by another caller.
            force_refresh = rejected_token is not None and self._token == rejected_token
            if force_refresh:
                self._invalidate_token()
            data = await self.fetch_stable_token(force_refresh=force_refresh)
            return self._cache_stable_token(data)

    def _invalidate_token(self) -> None:
        self._token = None
        self._token_expiry = 0.0
        if self._cache_path and self._cache_path.exists():
            try:
                self._cache_path.unlink()
            except OSError:
                pass

    # ---------------- generic helpers ----------------

    async def call_response(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
    ) -> httpx.Response:
        """Keep upstream bytes; retry rejected credentials once, including JSON errors
        labeled text/plain by WeChat's media endpoints.
        """
        rejected_token = None
        for attempt in range(2):
            token = await self.get_cached_access_token(rejected_token=rejected_token)
            q = {"access_token": token, **(params or {})}
            response = await self._client.request(
                method, path, params=q, json=json, data=data, files=files
            )
            try:
                payload = response.json()
            except ValueError:
                return response
            if (
                isinstance(payload, dict)
                and payload.get("errcode") in (40001, 42001)
                and attempt == 0
            ):
                rejected_token = token
                continue
            return response
        return response

    async def call_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """JSON-based authenticated call with one credential-recovery attempt."""
        response = await self.call_response(method, path, params=params, json=json)
        return response.json()

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
        response = await self.call_response(method, path, params=params, data=data, files=files)
        return response.json()

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
