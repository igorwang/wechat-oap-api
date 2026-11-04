import base64
import json

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from fastapi_mcp.types import HTTPRequestInfo

from app.config import settings
from main import app, mcp

BASE = settings.wechat_api_base
PNG = b"\x89PNG\r\n\x1a\n\xff\x00"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as client:
        yield client


def token_route(mock):
    return mock.post("/cgi-bin/stable_token").mock(
        return_value=httpx.Response(200, json={"access_token": "VALID", "expires_in": 7200})
    )


@pytest.mark.parametrize("content,content_type", [(PNG, "image/png"), (b"\xff\xfb\x00audio", "audio/mpeg")])
def test_permanent_material_raw_download_keeps_bytes_and_type(client, content, content_type):
    with respx.mock(base_url=BASE) as mock:
        token_route(mock)
        mock.post("/cgi-bin/material/get_material").mock(
            return_value=httpx.Response(200, content=content, headers={"content-type": content_type})
        )
        response = client.post("/wechat/material/permanent/get?response_format=raw", json={"media_id": "M"})
    assert response.status_code == 200
    assert response.content == content
    assert response.headers["content-type"] == content_type


def test_permanent_binary_defaults_to_lossless_json(client):
    with respx.mock(base_url=BASE) as mock:
        token_route(mock)
        mock.post("/cgi-bin/material/get_material").mock(
            return_value=httpx.Response(200, content=PNG, headers={"content-type": "image/png"})
        )
        response = client.post("/wechat/material/permanent/get", json={"media_id": "M"})
    result = response.json()
    assert result["encoding"] == "base64"
    assert result["content_type"] == "image/png"
    assert base64.b64decode(result["data"], validate=True) == PNG


@pytest.mark.parametrize("data", [
    {"news_item": [{"title": "Title", "content": "<p>body</p>"}]},
    {"title": "Video", "description": "Description", "down_url": "https://example.com/video"},
    {"errcode": 40007, "errmsg": "invalid media_id"},
])
@pytest.mark.parametrize("response_format", ["raw", "base64"])
def test_material_json_stays_json_regardless_of_format_and_upstream_mime(client, data, response_format):
    with respx.mock(base_url=BASE) as mock:
        token_route(mock)
        mock.post("/cgi-bin/material/get_material").mock(return_value=httpx.Response(
            200, content=json.dumps(data).encode(), headers={"content-type": "text/plain"},
        ))
        response = client.post(f"/wechat/material/permanent/get?response_format={response_format}", json={"media_id": "M"})
    assert response.json() == data
    assert response.headers["content-type"].startswith("application/json")


@pytest.mark.parametrize("errcode", [40001, 42001])
def test_binary_download_recovers_from_plain_text_json_auth_error(client, errcode):
    with respx.mock(base_url=BASE) as mock:
        tokens = mock.post("/cgi-bin/stable_token").mock(side_effect=[
            httpx.Response(200, json={"access_token": "OLD", "expires_in": 7200}),
            httpx.Response(200, json={"access_token": "NEW", "expires_in": 7200}),
        ])
        material = mock.post("/cgi-bin/material/get_material").mock(side_effect=[
            httpx.Response(200, content=json.dumps({"errcode": errcode, "errmsg": "invalid token"}).encode(),
                headers={"content-type": "text/plain"}),
            httpx.Response(200, content=PNG, headers={"content-type": "image/png"}),
        ])
        response = client.post("/wechat/material/permanent/get?response_format=raw", json={"media_id": "M"})
    assert response.content == PNG
    assert material.call_count == 2
    assert [json.loads(call.request.content)["force_refresh"] for call in tokens.calls] == [False, True]
    assert material.calls[1].request.url.params["access_token"] == "NEW"


@pytest.mark.parametrize("errcode", [40001, 42001])
def test_repeated_material_auth_failure_is_returned_after_one_retry(client, errcode):
    error = {"errcode": errcode, "errmsg": "still invalid"}
    with respx.mock(base_url=BASE) as mock:
        tokens = token_route(mock)
        material = mock.post("/cgi-bin/material/get_material").mock(
            return_value=httpx.Response(200, json=error)
        )
        response = client.post("/wechat/material/permanent/get", json={"media_id": "M"})
    assert response.json() == error
    assert material.call_count == 2
    assert tokens.call_count == 2


def test_raw_material_preserves_upstream_http_failure(client):
    with respx.mock(base_url=BASE) as mock:
        token_route(mock)
        mock.post("/cgi-bin/material/get_material").mock(
            return_value=httpx.Response(503, content=b"unavailable", headers={"content-type": "text/plain"})
        )
        response = client.post("/wechat/material/permanent/get?response_format=raw", json={"media_id": "M"})
    assert response.status_code == 503
    assert response.content == b"unavailable"


async def test_material_get_binary_through_real_mcp_executor(monkeypatch):
    api_key = "mcp-test-only-key"
    monkeypatch.setattr(settings, "api_key", api_key)
    request_info = HTTPRequestInfo(method="POST", path="/mcp",
        headers={settings.api_key_header.lower(): api_key}, cookies={}, query_params={}, body=None)
    with respx.mock(base_url=BASE) as mock:
        token_route(mock)
        material = mock.post("/cgi-bin/material/get_material").mock(
            return_value=httpx.Response(200, content=PNG, headers={"content-type": "image/png"})
        )
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as tool_client:
            content = await mcp._execute_api_tool(client=tool_client, tool_name="material_get",
                arguments={"media_id": "M"}, operation_map=mcp.operation_map, http_request_info=request_info)
    assert len(content) == 1
    result = json.loads(content[0].text)
    assert result["encoding"] == "base64"
    assert result["content_type"] == "image/png"
    assert base64.b64decode(result["data"], validate=True) == PNG
    assert json.loads(material.calls.last.request.content) == {"media_id": "M"}


def test_material_openapi_describes_json_raw_bytes_and_safe_default():
    operation = app.openapi()["paths"]["/wechat/material/permanent/get"]["post"]
    formats = next(p for p in operation["parameters"] if p["name"] == "response_format")
    assert formats["schema"]["default"] == "base64"
    assert set(formats["schema"]["enum"]) == {"base64", "raw"}
    content = operation["responses"]["200"]["content"]
    assert content["application/json"]["schema"]["type"] == "object"
    assert content["application/octet-stream"]["schema"] == {"type": "string", "format": "binary"}
