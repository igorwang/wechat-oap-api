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


def test_submit(client):
    with respx.mock(base_url=BASE) as mock:
        _token_mock(mock)
        route = mock.post("/cgi-bin/freepublish/submit").mock(
            return_value=httpx.Response(200, json={"errcode": 0, "publish_id": "P1"})
        )
        r = client.post("/wechat/freepublish/submit", json={"media_id": "M1"})
        assert r.status_code == 200
        assert r.json()["publish_id"] == "P1"
        assert b'"media_id":"M1"' in route.calls.last.request.content
        assert route.calls.last.request.url.params["access_token"] == "T"


def test_get_status(client):
    with respx.mock(base_url=BASE) as mock:
        _token_mock(mock)
        mock.post("/cgi-bin/freepublish/get").mock(
            return_value=httpx.Response(200, json={"publish_status": 0})
        )
        r = client.post("/wechat/freepublish/get", json={"publish_id": "P1"})
        assert r.status_code == 200
        assert r.json()["publish_status"] == 0


def test_delete(client):
    with respx.mock(base_url=BASE) as mock:
        _token_mock(mock)
        route = mock.post("/cgi-bin/freepublish/delete").mock(
            return_value=httpx.Response(200, json={"errcode": 0})
        )
        r = client.post(
            "/wechat/freepublish/delete", json={"article_id": "A1", "index": 2}
        )
        assert r.status_code == 200
        body = route.calls.last.request.content
        assert b'"article_id":"A1"' in body
        assert b'"index":2' in body


def test_batchget(client):
    with respx.mock(base_url=BASE) as mock:
        _token_mock(mock)
        route = mock.post("/cgi-bin/freepublish/batchget").mock(
            return_value=httpx.Response(200, json={"total_count": 0, "item": []})
        )
        r = client.post(
            "/wechat/freepublish/batchget",
            json={"offset": 0, "count": 5, "no_content": 1},
        )
        assert r.status_code == 200
        body = route.calls.last.request.content
        assert b'"no_content":1' in body


def test_getarticle(client):
    with respx.mock(base_url=BASE) as mock:
        _token_mock(mock)
        mock.post("/cgi-bin/freepublish/getarticle").mock(
            return_value=httpx.Response(200, json={"news_item": []})
        )
        r = client.post("/wechat/freepublish/getarticle", json={"article_id": "A1"})
        assert r.status_code == 200
        assert r.json() == {"news_item": []}
