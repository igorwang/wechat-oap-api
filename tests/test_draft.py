import json

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
    mock.post("/cgi-bin/stable_token").mock(
        return_value=httpx.Response(200, json={"access_token": "T", "expires_in": 7200})
    )


SAMPLE_ARTICLE = {
    "title": "Hello",
    "author": "me",
    "content": "<p>body</p>",
    "thumb_media_id": "TM1",
}


def test_add(client):
    with respx.mock(base_url=BASE) as mock:
        _token_mock(mock)
        route = mock.post("/cgi-bin/draft/add").mock(
            return_value=httpx.Response(200, json={"media_id": "NEW"})
        )
        r = client.post("/wechat/draft/add", json={"articles": [SAMPLE_ARTICLE]})
        assert r.status_code == 200
        assert r.json()["media_id"] == "NEW"
        body = route.calls.last.request.content
        assert b'"thumb_media_id":"TM1"' in body


def test_update(client):
    with respx.mock(base_url=BASE) as mock:
        _token_mock(mock)
        route = mock.post("/cgi-bin/draft/update").mock(
            return_value=httpx.Response(200, json={"errcode": 0})
        )
        r = client.post(
            "/wechat/draft/update",
            json={"media_id": "M", "index": 0, "articles": SAMPLE_ARTICLE},
        )
        assert r.status_code == 200
        body = route.calls.last.request.content
        assert b'"index":0' in body


@pytest.mark.parametrize("operation", ["add", "update"])
def test_picture_draft_without_legacy_thumbnail(client, operation):
    article = {
        "article_type": "newspic",
        "title": "Pictures",
        "content": "Picture caption",
        "image_info": {"image_list": [{"image_media_id": "IMG1"}]},
        "cover_info": {"crop_percent_list": [{"ratio": "1_1", "x1": 0, "y1": 0, "x2": 1, "y2": 1}]},
        "product_info": {"footer_product": {"product_key": "example"}},
    }
    payload = {"articles": [article]} if operation == "add" else {
        "media_id": "M", "index": 0, "articles": article,
    }
    with respx.mock(base_url=BASE) as mock:
        _token_mock(mock)
        route = mock.post(f"/cgi-bin/draft/{operation}").mock(
            return_value=httpx.Response(200, json={"media_id": "M", "errcode": 0})
        )
        response = client.post(f"/wechat/draft/{operation}", json=payload)
        assert response.status_code == 200
        sent = json.loads(route.calls.last.request.content)["articles"]
        if operation == "add":
            sent = sent[0]
        assert "thumb_media_id" not in sent
        for field, value in article.items():
            assert sent[field] == value


@pytest.mark.parametrize("article", [
    {"title": "News", "content": "body"},
    {"article_type": "newspic", "title": "Pictures", "content": "caption"},
    {"article_type": "newspic", "title": "Pictures", "content": "caption", "image_info": {"image_list": []}},
    {"article_type": "newspic", "title": "Pictures", "content": "caption", "image_info": {
        "image_list": [{"image_media_id": "IMG"}] * 21,
    }},
])
def test_draft_requires_type_specific_media(client, article):
    with respx.mock:
        response = client.post("/wechat/draft/add", json={"articles": [article]})
    assert response.status_code == 422


def test_get(client):
    with respx.mock(base_url=BASE) as mock:
        _token_mock(mock)
        mock.post("/cgi-bin/draft/get").mock(
            return_value=httpx.Response(200, json={"news_item": []})
        )
        r = client.post("/wechat/draft/get", json={"media_id": "M"})
        assert r.status_code == 200


def test_batchget(client):
    with respx.mock(base_url=BASE) as mock:
        _token_mock(mock)
        mock.post("/cgi-bin/draft/batchget").mock(
            return_value=httpx.Response(200, json={"total_count": 0, "item": []})
        )
        r = client.post("/wechat/draft/batchget", json={"offset": 0, "count": 5})
        assert r.status_code == 200


def test_count(client):
    with respx.mock(base_url=BASE) as mock:
        _token_mock(mock)
        mock.get("/cgi-bin/draft/count").mock(
            return_value=httpx.Response(200, json={"total_count": 42})
        )
        r = client.get("/wechat/draft/count")
        assert r.status_code == 200
        assert r.json()["total_count"] == 42


def test_delete(client):
    with respx.mock(base_url=BASE) as mock:
        _token_mock(mock)
        mock.post("/cgi-bin/draft/delete").mock(
            return_value=httpx.Response(200, json={"errcode": 0})
        )
        r = client.post("/wechat/draft/delete", json={"media_id": "M"})
        assert r.status_code == 200


def test_switch(client):
    with respx.mock(base_url=BASE) as mock:
        _token_mock(mock)
        route = mock.post("/cgi-bin/draft/switch").mock(
            return_value=httpx.Response(200, json={"is_open": 0})
        )
        r = client.post("/wechat/draft/switch", json={"checkonly": 1})
        assert r.status_code == 200
        assert route.calls.last.request.url.params["checkonly"] == "1"


def test_product_cardinfo(client):
    with respx.mock(base_url=BASE) as mock:
        _token_mock(mock)
        mock.post("/channels/ec/service/product/getcardinfo").mock(
            return_value=httpx.Response(200, json={"errcode": 0, "card": {}})
        )
        r = client.post(
            "/wechat/draft/product-cardinfo",
            json={"url": "https://channels.weixin.qq.com/p/xyz"},
        )
        assert r.status_code == 200
