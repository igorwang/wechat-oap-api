import asyncio
import json

import httpx
import respx

from app.config import settings
from app.wechat import WeChatClient


BASE = settings.wechat_api_base


async def test_concurrent_fetch_deduplicates():
    """Many parallel callers on a cold cache should trigger exactly one /cgi-bin/token."""
    client = WeChatClient(cache_path="")
    async with respx.mock(base_url=BASE) as mock:
        route = mock.get("/cgi-bin/token").mock(
            return_value=httpx.Response(
                200, json={"access_token": "ONCE", "expires_in": 7200}
            )
        )
        tokens = await asyncio.gather(
            *[client.get_cached_access_token() for _ in range(20)]
        )
        assert set(tokens) == {"ONCE"}
        assert route.call_count == 1


async def test_file_persistence_survives_new_instance(tmp_path):
    """A second client pointed at the same cache file reuses the token without a fetch."""
    cache_file = tmp_path / "token.json"
    client_a = WeChatClient(cache_path=str(cache_file))
    async with respx.mock(base_url=BASE) as mock:
        mock.get("/cgi-bin/token").mock(
            return_value=httpx.Response(
                200, json={"access_token": "PERSISTED", "expires_in": 7200}
            )
        )
        assert await client_a.get_cached_access_token() == "PERSISTED"

    assert cache_file.exists()
    data = json.loads(cache_file.read_text())
    assert data["access_token"] == "PERSISTED"
    assert data["appid"] == settings.wechat_appid

    # New instance, same file: should load from disk without hitting WeChat.
    client_b = WeChatClient(cache_path=str(cache_file))
    async with respx.mock(base_url=BASE, assert_all_called=False) as mock:
        token_route = mock.get("/cgi-bin/token")
        assert await client_b.get_cached_access_token() == "PERSISTED"
        assert token_route.call_count == 0


async def test_40001_clears_persisted_cache(tmp_path):
    """When WeChat rejects the token, we must invalidate and refresh (also wiping disk)."""
    cache_file = tmp_path / "token.json"
    client = WeChatClient(cache_path=str(cache_file))
    async with respx.mock(base_url=BASE) as mock:
        mock.get("/cgi-bin/token").mock(
            side_effect=[
                httpx.Response(
                    200, json={"access_token": "OLD", "expires_in": 7200}
                ),
                httpx.Response(
                    200, json={"access_token": "NEW", "expires_in": 7200}
                ),
            ]
        )
        mock.get("/cgi-bin/getcallbackip").mock(
            side_effect=[
                httpx.Response(200, json={"errcode": 40001, "errmsg": "bad token"}),
                httpx.Response(200, json={"ip_list": ["9.9.9.9"]}),
            ]
        )
        data = await client.get_callback_ip()
        assert data == {"ip_list": ["9.9.9.9"]}
        # New token must have been persisted.
        saved = json.loads(cache_file.read_text())
        assert saved["access_token"] == "NEW"


async def test_cache_file_ignored_when_appid_mismatches(tmp_path):
    cache_file = tmp_path / "token.json"
    cache_file.write_text(
        json.dumps(
            {
                "appid": "someone_elses_appid",
                "access_token": "STALE",
                "expiry": 9999999999.0,
            }
        )
    )
    client = WeChatClient(cache_path=str(cache_file))
    async with respx.mock(base_url=BASE) as mock:
        mock.get("/cgi-bin/token").mock(
            return_value=httpx.Response(
                200, json={"access_token": "FRESH", "expires_in": 7200}
            )
        )
        assert await client.get_cached_access_token() == "FRESH"
