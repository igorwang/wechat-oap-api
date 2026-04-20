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


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_get_access_token_route(client):
    with respx.mock(base_url=BASE) as mock:
        mock.get("/cgi-bin/token").mock(
            return_value=httpx.Response(
                200, json={"access_token": "TT", "expires_in": 7200}
            )
        )
        r = client.get("/wechat/token")
        assert r.status_code == 200
        assert r.json()["access_token"] == "TT"


def test_stable_token_route(client):
    with respx.mock(base_url=BASE) as mock:
        mock.post("/cgi-bin/stable_token").mock(
            return_value=httpx.Response(
                200, json={"access_token": "STAB", "expires_in": 7200}
            )
        )
        r = client.get("/wechat/stable-token?force_refresh=true")
        assert r.status_code == 200
        assert r.json()["access_token"] == "STAB"


def test_callback_check_route(client):
    with respx.mock(base_url=BASE) as mock:
        mock.get("/cgi-bin/token").mock(
            return_value=httpx.Response(
                200, json={"access_token": "T", "expires_in": 7200}
            )
        )
        mock.post("/cgi-bin/callback/check").mock(
            return_value=httpx.Response(200, json={"errcode": 0, "dns": []})
        )
        r = client.post(
            "/wechat/callback/check",
            json={"action": "all", "check_operator": "DEFAULT"},
        )
        assert r.status_code == 200
        assert r.json()["errcode"] == 0


def test_api_domain_ip_route(client):
    with respx.mock(base_url=BASE) as mock:
        mock.get("/cgi-bin/token").mock(
            return_value=httpx.Response(
                200, json={"access_token": "T", "expires_in": 7200}
            )
        )
        mock.get("/cgi-bin/get_api_domain_ip").mock(
            return_value=httpx.Response(200, json={"ip_list": ["1.1.1.1"]})
        )
        r = client.get("/wechat/api-domain-ip")
        assert r.status_code == 200
        assert r.json()["ip_list"] == ["1.1.1.1"]


def test_callback_ip_route(client):
    with respx.mock(base_url=BASE) as mock:
        mock.get("/cgi-bin/token").mock(
            return_value=httpx.Response(
                200, json={"access_token": "T", "expires_in": 7200}
            )
        )
        mock.get("/cgi-bin/getcallbackip").mock(
            return_value=httpx.Response(200, json={"ip_list": ["2.2.2.2"]})
        )
        r = client.get("/wechat/callback-ip")
        assert r.status_code == 200
        assert r.json()["ip_list"] == ["2.2.2.2"]


def test_clear_quota_route(client):
    with respx.mock(base_url=BASE) as mock:
        mock.get("/cgi-bin/token").mock(
            return_value=httpx.Response(
                200, json={"access_token": "T", "expires_in": 7200}
            )
        )
        mock.post("/cgi-bin/clear_quota").mock(
            return_value=httpx.Response(200, json={"errcode": 0, "errmsg": "ok"})
        )
        r = client.post("/wechat/clear-quota", json={})
        assert r.status_code == 200
        assert r.json() == {"errcode": 0, "errmsg": "ok"}


def test_mcp_route_mounted():
    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/mcp" in paths


def test_wechat_tag_operations_in_openapi():
    schema = app.openapi()
    wechat_ops = {
        op.get("operationId")
        for path_item in schema["paths"].values()
        for op in path_item.values()
        if "wechat" in (op.get("tags") or [])
    }
    # All 6 基础接口 must be present; group routers add the rest.
    expected_basic = {
        "get_access_token",
        "get_stable_token",
        "callback_check",
        "get_api_domain_ip",
        "get_callback_ip",
        "clear_quota",
    }
    assert expected_basic <= wechat_ops
    # Full coverage check: at least one op per group.
    assert any(o.startswith("freepublish_") for o in wechat_ops)
    assert any(o.startswith("draft_") for o in wechat_ops)
    assert any(o.startswith("material_") for o in wechat_ops)
    assert any(o.startswith("message_") for o in wechat_ops)


def test_mcp_whitelist_draft_and_material_only():
    """MCP must expose ONLY draft + material + healthz; publish/message are HTTP-only.

    This is the guard for the 'compose drafts; I'll publish by hand' workflow.
    """
    from main import MCP_TOOLS

    assert set(MCP_TOOLS) == {
        "healthz",
        "draft_add",
        "draft_update",
        "draft_get",
        "draft_batchget",
        "draft_count",
        "draft_delete",
        "draft_switch",
        "draft_product_cardinfo",
        "material_get",
        "material_count",
        "material_batchget",
        "material_delete",
        "material_uploadimg",
        "material_add",
        "material_temp_upload",
        "material_temp_get",
        "material_temp_get_jssdk",
    }
    # Explicitly must-NOT-be-there: publish + message.
    assert not any(t.startswith("freepublish_") for t in MCP_TOOLS)
    assert not any(t.startswith("message_") for t in MCP_TOOLS)
    # HTTP routes for the excluded groups still exist (agent can't reach them,
    # but humans using /docs or curl can).
    http_ops = {
        op.get("operationId")
        for path_item in app.openapi()["paths"].values()
        for op in path_item.values()
    }
    assert "freepublish_submit" in http_ops
    assert "message_mass_sendall" in http_ops
