import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.config import settings
from main import app

BASE = settings.wechat_api_base


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _token_mock(mock):
    mock.get("/cgi-bin/token").mock(
        return_value=httpx.Response(200, json={"access_token": "T", "expires_in": 7200})
    )


# ---------- mass ----------


def test_mass_delete(client):
    with respx.mock(base_url=BASE) as mock:
        _token_mock(mock)
        route = mock.post("/cgi-bin/message/mass/delete").mock(
            return_value=httpx.Response(200, json={"errcode": 0})
        )
        r = client.post(
            "/wechat/message/mass/delete", json={"msg_id": 123, "article_idx": 1}
        )
        assert r.status_code == 200
        body = route.calls.last.request.content
        assert b'"msg_id":123' in body
        assert b'"article_idx":1' in body


def test_mass_speed_get(client):
    with respx.mock(base_url=BASE) as mock:
        _token_mock(mock)
        mock.post("/cgi-bin/message/mass/speed/get").mock(
            return_value=httpx.Response(200, json={"speed": 2, "realspeed": 10})
        )
        r = client.post("/wechat/message/mass/speed/get")
        assert r.status_code == 200
        assert r.json()["speed"] == 2


def test_mass_speed_set(client):
    with respx.mock(base_url=BASE) as mock:
        _token_mock(mock)
        route = mock.post("/cgi-bin/message/mass/speed/set").mock(
            return_value=httpx.Response(200, json={"errcode": 0})
        )
        r = client.post("/wechat/message/mass/speed/set", json={"speed": 2})
        assert r.status_code == 200
        assert b'"speed":2' in route.calls.last.request.content


def test_mass_speed_set_validates_range(client):
    # No WeChat call should be made — client-side validation (0..4).
    r = client.post("/wechat/message/mass/speed/set", json={"speed": 5})
    assert r.status_code == 422


def test_mass_get(client):
    with respx.mock(base_url=BASE) as mock:
        _token_mock(mock)
        mock.post("/cgi-bin/message/mass/get").mock(
            return_value=httpx.Response(200, json={"msg_id": 1, "msg_status": "SEND_SUCCESS"})
        )
        r = client.post("/wechat/message/mass/get", json={"msg_id": "1"})
        assert r.status_code == 200


def test_mass_preview(client):
    with respx.mock(base_url=BASE) as mock:
        _token_mock(mock)
        route = mock.post("/cgi-bin/message/mass/preview").mock(
            return_value=httpx.Response(200, json={"errcode": 0})
        )
        r = client.post(
            "/wechat/message/mass/preview",
            json={"touser": "openid_xxx", "msgtype": "text", "text": {"content": "hi"}},
        )
        assert r.status_code == 200
        body = route.calls.last.request.content
        assert b'"touser":"openid_xxx"' in body
        assert b'"text":{"content":"hi"}' in body


def test_mass_sendall(client):
    with respx.mock(base_url=BASE) as mock:
        _token_mock(mock)
        mock.post("/cgi-bin/message/mass/sendall").mock(
            return_value=httpx.Response(200, json={"errcode": 0, "msg_id": 9})
        )
        r = client.post(
            "/wechat/message/mass/sendall",
            json={
                "filter": {"is_to_all": False, "tag_id": 2},
                "msgtype": "text",
                "text": {"content": "hi all"},
            },
        )
        assert r.status_code == 200


def test_mass_uploadnews(client):
    with respx.mock(base_url=BASE) as mock:
        _token_mock(mock)
        mock.post("/cgi-bin/media/uploadnews").mock(
            return_value=httpx.Response(200, json={"media_id": "MN"})
        )
        r = client.post(
            "/wechat/message/mass/uploadnews",
            json={"articles": [{"title": "t", "thumb_media_id": "T", "content": "c"}]},
        )
        assert r.status_code == 200
        assert r.json()["media_id"] == "MN"


# ---------- subscribe ----------


def test_subscribe_send(client):
    with respx.mock(base_url=BASE) as mock:
        _token_mock(mock)
        route = mock.post("/cgi-bin/message/template/subscribe").mock(
            return_value=httpx.Response(200, json={"errcode": 0})
        )
        r = client.post(
            "/wechat/message/subscribe/send",
            json={
                "touser": "openid",
                "template_id": "tpl",
                "scene": "1001",
                "title": "hi",
                "data": {"content": {"value": "x", "color": "#000"}},
            },
        )
        assert r.status_code == 200
        body = route.calls.last.request.content
        assert b'"scene":"1001"' in body


# ---------- autoreply ----------


def test_autoreply_info(client):
    with respx.mock(base_url=BASE) as mock:
        _token_mock(mock)
        mock.get("/cgi-bin/get_current_autoreply_info").mock(
            return_value=httpx.Response(200, json={"is_add_friend_reply_open": 1})
        )
        r = client.get("/wechat/message/autoreply/info")
        assert r.status_code == 200
        assert r.json()["is_add_friend_reply_open"] == 1
