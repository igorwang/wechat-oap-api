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


# ---------- permanent ----------


def test_get_permanent(client):
    with respx.mock(base_url=BASE) as mock:
        _token_mock(mock)
        mock.post("/cgi-bin/material/get_material").mock(
            return_value=httpx.Response(200, json={"news_item": []})
        )
        r = client.post("/wechat/material/permanent/get", json={"media_id": "M"})
        assert r.status_code == 200


def test_count_permanent(client):
    with respx.mock(base_url=BASE) as mock:
        _token_mock(mock)
        mock.get("/cgi-bin/material/get_materialcount").mock(
            return_value=httpx.Response(
                200,
                json={"voice_count": 1, "video_count": 2, "image_count": 3, "news_count": 4},
            )
        )
        r = client.get("/wechat/material/permanent/count")
        assert r.status_code == 200
        assert r.json()["image_count"] == 3


def test_batchget_permanent(client):
    with respx.mock(base_url=BASE) as mock:
        _token_mock(mock)
        route = mock.post("/cgi-bin/material/batchget_material").mock(
            return_value=httpx.Response(200, json={"total_count": 0, "item": []})
        )
        r = client.post(
            "/wechat/material/permanent/batchget",
            json={"type": "image", "offset": 0, "count": 10},
        )
        assert r.status_code == 200
        assert b'"type":"image"' in route.calls.last.request.content


def test_delete_permanent(client):
    with respx.mock(base_url=BASE) as mock:
        _token_mock(mock)
        mock.post("/cgi-bin/material/del_material").mock(
            return_value=httpx.Response(200, json={"errcode": 0})
        )
        r = client.post("/wechat/material/permanent/delete", json={"media_id": "M"})
        assert r.status_code == 200


def test_uploadimg(client):
    with respx.mock(base_url=BASE) as mock:
        _token_mock(mock)
        route = mock.post("/cgi-bin/media/uploadimg").mock(
            return_value=httpx.Response(200, json={"url": "https://mmbiz/xxx"})
        )
        r = client.post(
            "/wechat/material/permanent/uploadimg",
            files={"media": ("a.png", b"fakebytes", "image/png")},
        )
        assert r.status_code == 200
        assert r.json()["url"] == "https://mmbiz/xxx"
        # Multipart body sent to WeChat must carry the file content.
        assert b"fakebytes" in route.calls.last.request.content


def test_add_material_image(client):
    with respx.mock(base_url=BASE) as mock:
        _token_mock(mock)
        route = mock.post("/cgi-bin/material/add_material").mock(
            return_value=httpx.Response(200, json={"media_id": "PM", "url": "u"})
        )
        r = client.post(
            "/wechat/material/permanent/add?type=image",
            files={"media": ("a.png", b"img", "image/png")},
        )
        assert r.status_code == 200
        assert route.calls.last.request.url.params["type"] == "image"
        assert route.calls.last.request.url.params["access_token"] == "T"


def test_add_material_video_requires_description(client):
    with respx.mock(base_url=BASE) as mock:
        _token_mock(mock)
        route = mock.post("/cgi-bin/material/add_material").mock(
            return_value=httpx.Response(200, json={"media_id": "VM"})
        )
        r = client.post(
            "/wechat/material/permanent/add?type=video",
            files={"media": ("v.mp4", b"vid", "video/mp4")},
            data={"title": "hi", "introduction": "desc"},
        )
        assert r.status_code == 200
        body = route.calls.last.request.content
        assert b"description" in body
        assert b'"title":' in body and b'"introduction":' in body


# ---------- temporary ----------


def test_temp_upload(client):
    with respx.mock(base_url=BASE) as mock:
        _token_mock(mock)
        route = mock.post("/cgi-bin/media/upload").mock(
            return_value=httpx.Response(200, json={"media_id": "TMP", "type": "image"})
        )
        r = client.post(
            "/wechat/material/temporary/upload?type=image",
            files={"media": ("x.png", b"bytes", "image/png")},
        )
        assert r.status_code == 200
        assert route.calls.last.request.url.params["type"] == "image"


def test_temp_get_binary(client):
    with respx.mock(base_url=BASE) as mock:
        _token_mock(mock)
        mock.get("/cgi-bin/media/get").mock(
            return_value=httpx.Response(
                200, content=b"\x89PNG\r\n", headers={"content-type": "image/png"}
            )
        )
        r = client.get("/wechat/material/temporary/get?media_id=X")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("image/png")
        assert r.content.startswith(b"\x89PNG")


def test_temp_get_jssdk(client):
    with respx.mock(base_url=BASE) as mock:
        _token_mock(mock)
        mock.get("/cgi-bin/media/get/jssdk").mock(
            return_value=httpx.Response(
                200, content=b"voicedata", headers={"content-type": "audio/mpeg"}
            )
        )
        r = client.get("/wechat/material/temporary/get-jssdk?media_id=V1")
        assert r.status_code == 200
        assert r.content == b"voicedata"
