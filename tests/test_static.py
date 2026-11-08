"""静态资源服务 — 公众号二维码等随镜像分发的资产."""

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from main import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.mark.parametrize(
    ("filename", "content_type", "signature"),
    [
        ("qrcode-official-account.jpg", "image/jpeg", b"\xff\xd8"),
        ("feyn-group-qrcode.png", "image/png", b"\x89PNG\r\n\x1a\n"),
    ],
)
def test_qrcode_is_served(client, filename, content_type, signature):
    r = client.get(f"/static/{filename}")
    assert r.status_code == 200
    assert r.headers["content-type"] == content_type
    assert r.content.startswith(signature)


@pytest.mark.parametrize("filename", ["qrcode-official-account.jpg", "feyn-group-qrcode.png"])
def test_static_is_public_even_when_api_key_enabled(client, monkeypatch, filename):
    """静态资源要能被微信/浏览器直接取用，不该被 API key 拦住."""
    monkeypatch.setattr(settings, "api_key", "sekret")
    r = client.get(f"/static/{filename}")
    assert r.status_code == 200
