import httpx
import pytest
import respx

from app.config import settings


BASE = settings.wechat_api_base


async def test_fetch_access_token_success(fresh_client):
    async with respx.mock(base_url=BASE) as mock:
        mock.get("/cgi-bin/token").mock(
            return_value=httpx.Response(
                200, json={"access_token": "TOK123", "expires_in": 7200}
            )
        )
        data = await fresh_client.fetch_access_token()
        assert data == {"access_token": "TOK123", "expires_in": 7200}
        call = mock.calls.last
        assert call.request.url.params["grant_type"] == "client_credential"
        assert call.request.url.params["appid"] == "test_appid"
        assert call.request.url.params["secret"] == "test_secret"


async def test_fetch_access_token_error_passthrough(fresh_client):
    async with respx.mock(base_url=BASE) as mock:
        mock.get("/cgi-bin/token").mock(
            return_value=httpx.Response(
                200, json={"errcode": 40013, "errmsg": "invalid appid"}
            )
        )
        data = await fresh_client.fetch_access_token()
        assert data["errcode"] == 40013


async def test_fetch_stable_token_posts_json(fresh_client):
    async with respx.mock(base_url=BASE) as mock:
        route = mock.post("/cgi-bin/stable_token").mock(
            return_value=httpx.Response(
                200, json={"access_token": "STAB1", "expires_in": 7200}
            )
        )
        data = await fresh_client.fetch_stable_token(force_refresh=True)
        assert data["access_token"] == "STAB1"
        body = route.calls.last.request.content
        assert b'"force_refresh":true' in body
        assert b'"grant_type":"client_credential"' in body


async def test_cached_token_reuses(fresh_client):
    async with respx.mock(base_url=BASE) as mock:
        token_route = mock.get("/cgi-bin/token").mock(
            return_value=httpx.Response(
                200, json={"access_token": "CACHED", "expires_in": 7200}
            )
        )
        t1 = await fresh_client.get_cached_access_token()
        t2 = await fresh_client.get_cached_access_token()
        assert t1 == t2 == "CACHED"
        assert token_route.call_count == 1


async def test_cached_token_refreshes_on_40001(fresh_client):
    async with respx.mock(base_url=BASE) as mock:
        mock.get("/cgi-bin/token").mock(
            side_effect=[
                httpx.Response(200, json={"access_token": "OLD", "expires_in": 7200}),
                httpx.Response(200, json={"access_token": "NEW", "expires_in": 7200}),
            ]
        )
        cb_route = mock.get("/cgi-bin/getcallbackip").mock(
            side_effect=[
                httpx.Response(200, json={"errcode": 40001, "errmsg": "invalid token"}),
                httpx.Response(200, json={"ip_list": ["1.2.3.4"]}),
            ]
        )
        data = await fresh_client.get_callback_ip()
        assert data == {"ip_list": ["1.2.3.4"]}
        assert cb_route.call_count == 2
        # 2nd call must use the refreshed token
        assert cb_route.calls[1].request.url.params["access_token"] == "NEW"


async def test_callback_check_post_body(fresh_client):
    async with respx.mock(base_url=BASE) as mock:
        mock.get("/cgi-bin/token").mock(
            return_value=httpx.Response(
                200, json={"access_token": "T", "expires_in": 7200}
            )
        )
        route = mock.post("/cgi-bin/callback/check").mock(
            return_value=httpx.Response(200, json={"errcode": 0, "dns": []})
        )
        data = await fresh_client.callback_check(action="dns", check_operator="CHINANET")
        assert data["errcode"] == 0
        body = route.calls.last.request.content
        assert b'"action":"dns"' in body
        assert b'"check_operator":"CHINANET"' in body
        assert route.calls.last.request.url.params["access_token"] == "T"


async def test_get_api_domain_ip(fresh_client):
    async with respx.mock(base_url=BASE) as mock:
        mock.get("/cgi-bin/token").mock(
            return_value=httpx.Response(
                200, json={"access_token": "T", "expires_in": 7200}
            )
        )
        mock.get("/cgi-bin/get_api_domain_ip").mock(
            return_value=httpx.Response(200, json={"ip_list": ["10.0.0.1"]})
        )
        data = await fresh_client.get_api_domain_ip()
        assert data == {"ip_list": ["10.0.0.1"]}


async def test_clear_quota_defaults_to_env_appid(fresh_client):
    async with respx.mock(base_url=BASE) as mock:
        mock.get("/cgi-bin/token").mock(
            return_value=httpx.Response(
                200, json={"access_token": "T", "expires_in": 7200}
            )
        )
        route = mock.post("/cgi-bin/clear_quota").mock(
            return_value=httpx.Response(200, json={"errcode": 0, "errmsg": "ok"})
        )
        data = await fresh_client.clear_quota()
        assert data["errcode"] == 0
        assert b'"appid":"test_appid"' in route.calls.last.request.content


async def test_missing_credentials_raises(monkeypatch):
    from app import wechat as wechat_mod

    monkeypatch.setattr(wechat_mod.settings, "wechat_appid", "")
    monkeypatch.setattr(wechat_mod.settings, "wechat_appsecret", "")
    c = wechat_mod.WeChatClient()
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await c.fetch_access_token()
    assert exc.value.status_code == 500
