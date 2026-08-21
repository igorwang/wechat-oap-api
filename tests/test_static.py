"""静态资源服务 — 公众号二维码等随镜像分发的资产."""

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from main import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_qrcode_is_served(client):
    r = client.get("/static/qrcode-official-account.jpg")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/jpeg"
    assert r.content[:2] == b"\xff\xd8", "应是 JPEG 内容"


def test_static_is_public_even_when_api_key_enabled(client, monkeypatch):
    """静态资源要能被微信/浏览器直接取用，不该被 API key 拦住."""
    monkeypatch.setattr(settings, "api_key", "sekret")
    r = client.get("/static/qrcode-official-account.jpg")
    assert r.status_code == 200
