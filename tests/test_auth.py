"""API key auth tests — toggles via monkeypatching settings.api_key."""

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.config import settings
from main import app


BASE = settings.wechat_api_base


@pytest.fixture
def client():
    # Per-test client so the module-level test_api client isn't disturbed.
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def enable_auth(monkeypatch):
    monkeypatch.setattr(settings, "api_key", "secret123")
    yield "secret123"
    # monkeypatch auto-reverts


def test_no_auth_when_key_empty(client):
    # Default conftest leaves api_key="" → all paths open.
    r = client.get("/healthz")
    assert r.status_code == 200
    with respx.mock(base_url=BASE) as mock:
        mock.get("/cgi-bin/token").mock(
            return_value=httpx.Response(200, json={"access_token": "T", "expires_in": 7200})
        )
        r = client.get("/wechat/token")
        assert r.status_code == 200


def test_missing_api_key_rejected(client, enable_auth):
    r = client.get("/wechat/token")
    assert r.status_code == 401
    assert "API key" in r.json()["detail"]


def test_wrong_api_key_rejected(client, enable_auth):
    r = client.get("/wechat/token", headers={"X-API-Key": "wrong"})
    assert r.status_code == 401


def test_correct_api_key_accepted(client, enable_auth):
    with respx.mock(base_url=BASE) as mock:
        mock.get("/cgi-bin/token").mock(
            return_value=httpx.Response(200, json={"access_token": "T", "expires_in": 7200})
        )
        r = client.get("/wechat/token", headers={"X-API-Key": "secret123"})
        assert r.status_code == 200


def test_docs_exempt_even_when_auth_enabled(client, enable_auth):
    for path in ["/healthz", "/docs", "/openapi.json", "/redoc"]:
        r = client.get(path)
        assert r.status_code == 200, path


def test_mcp_endpoint_enforces_auth(client, enable_auth):
    # /mcp without key → 401.
    r = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        headers={"Accept": "application/json, text/event-stream"},
    )
    assert r.status_code == 401


def test_mcp_header_forwarding_configured():
    """FastApiMCP must forward x-api-key to internal tool calls, otherwise
    the middleware would reject them even when the MCP client authed properly."""
    from main import mcp as mcp_instance

    forwarded = {h.lower() for h in mcp_instance._forward_headers}
    assert "x-api-key" in forwarded


def test_case_insensitive_header(client, enable_auth):
    """HTTP header names are case-insensitive; lowercase must also work."""
    with respx.mock(base_url=BASE) as mock:
        mock.get("/cgi-bin/token").mock(
            return_value=httpx.Response(200, json={"access_token": "T", "expires_in": 7200})
        )
        r = client.get("/wechat/token", headers={"x-api-key": "secret123"})
        assert r.status_code == 200
