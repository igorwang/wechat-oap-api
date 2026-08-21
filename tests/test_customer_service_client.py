"""CustomerServiceClient — qyapi gettoken 缓存、sync_msg 增量拉取、发送消息."""

import httpx
import pytest
import respx

from app.customer_service.client import CustomerServiceClient

BASE = "https://qyapi.weixin.qq.com"


@pytest.fixture
def client(tmp_path):
    return CustomerServiceClient(
        corpid="test_corpid",
        secret="test_cs_secret",
        base_url=BASE,
        cursor_path=str(tmp_path / "cursor.json"),
    )


def _mock_token(mock, token="CSTOK1"):
    return mock.get("/cgi-bin/gettoken").mock(
        return_value=httpx.Response(200, json={"errcode": 0, "access_token": token, "expires_in": 7200})
    )


async def test_gettoken_uses_corpid_and_secret(client):
    async with respx.mock(base_url=BASE) as mock:
        _mock_token(mock)
        token = await client.get_access_token()
        assert token == "CSTOK1"
        params = mock.calls.last.request.url.params
        assert params["corpid"] == "test_corpid"
        assert params["corpsecret"] == "test_cs_secret"


async def test_gettoken_cached_between_calls(client):
    async with respx.mock(base_url=BASE) as mock:
        route = _mock_token(mock)
        t1 = await client.get_access_token()
        t2 = await client.get_access_token()
        assert t1 == t2 == "CSTOK1"
        assert route.call_count == 1


async def test_sync_msg_paginates_and_persists_cursor(client):
    async with respx.mock(base_url=BASE) as mock:
        _mock_token(mock)
        pages = [
            {"errcode": 0, "next_cursor": "CUR1", "has_more": 1,
             "msg_list": [{"msgid": "m1", "msgtype": "text", "origin": 3}]},
            {"errcode": 0, "next_cursor": "CUR2", "has_more": 0,
             "msg_list": [{"msgid": "m2", "msgtype": "text", "origin": 3}]},
        ]
        route = mock.post("/cgi-bin/kf/sync_msg").mock(
            side_effect=[httpx.Response(200, json=p) for p in pages]
        )
        msgs = await client.sync_msg(token="EVT_TOKEN", open_kfid="wk_test")
        assert [m["msgid"] for m in msgs] == ["m1", "m2"]
        # 第一页不带 cursor；第二页带上一页的 next_cursor；事件 token 每次都带
        import json

        first = json.loads(route.calls[0].request.content)
        second = json.loads(route.calls[1].request.content)
        assert "cursor" not in first or first["cursor"] == ""
        assert first["token"] == "EVT_TOKEN"
        assert first["open_kfid"] == "wk_test"
        assert second["cursor"] == "CUR1"


async def test_sync_msg_resumes_from_persisted_cursor(client):
    async with respx.mock(base_url=BASE) as mock:
        _mock_token(mock)
        route = mock.post("/cgi-bin/kf/sync_msg").mock(
            side_effect=[
                httpx.Response(200, json={"errcode": 0, "next_cursor": "CURX", "has_more": 0, "msg_list": []}),
                httpx.Response(200, json={"errcode": 0, "next_cursor": "CURY", "has_more": 0, "msg_list": []}),
            ]
        )
        await client.sync_msg()
        await client.sync_msg()
        import json

        second = json.loads(route.calls[1].request.content)
        assert second["cursor"] == "CURX"


async def test_send_text(client):
    async with respx.mock(base_url=BASE) as mock:
        _mock_token(mock)
        route = mock.post("/cgi-bin/kf/send_msg").mock(
            return_value=httpx.Response(200, json={"errcode": 0, "errmsg": "ok", "msgid": "SM1"})
        )
        data = await client.send_text(
            touser="ext_user1", open_kfid="wk_test", content="你好"
        )
        assert data["msgid"] == "SM1"
        import json

        body = json.loads(route.calls.last.request.content)
        assert body == {
            "touser": "ext_user1",
            "open_kfid": "wk_test",
            "msgtype": "text",
            "text": {"content": "你好"},
        }
        assert route.calls.last.request.url.params["access_token"] == "CSTOK1"


async def test_send_welcome_on_event(client):
    async with respx.mock(base_url=BASE) as mock:
        _mock_token(mock)
        route = mock.post("/cgi-bin/kf/send_msg_on_event").mock(
            return_value=httpx.Response(200, json={"errcode": 0, "errmsg": "ok", "msgid": "WM1"})
        )
        data = await client.send_welcome(code="WELCOME_CODE", content="欢迎咨询")
        assert data["msgid"] == "WM1"
        import json

        body = json.loads(route.calls.last.request.content)
        assert body == {
            "code": "WELCOME_CODE",
            "msgtype": "text",
            "text": {"content": "欢迎咨询"},
        }
