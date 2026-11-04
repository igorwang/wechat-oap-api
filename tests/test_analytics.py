"""Article operations contracts, with no real account or network access."""

import json
from datetime import date, datetime, timezone

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from fastapi_mcp.types import HTTPRequestInfo

from app.config import settings
from main import app, mcp

BASE = settings.wechat_api_base
ENDPOINTS = [
    ("article-read", "getarticleread", "analytics_article_read"),
    ("article-share", "getarticleshare", "analytics_article_share"),
    ("account-summary", "getbizsummary", "analytics_account_summary"),
    ("article-details", "getarticletotaldetail", "analytics_article_details"),
]
DAY = {"begin_date": "2025-11-01", "end_date": "2025-11-01"}


@pytest.mark.parametrize("hour,minute,expected", [
    (15, 59, date(2026, 11, 3)),
    (16, 0, date(2026, 11, 4)),
])
def test_reporting_day_rolls_over_at_beijing_midnight(monkeypatch, hour, minute, expected):
    from app.routers import analytics

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 11, 3, hour, minute, tzinfo=timezone.utc).astimezone(tz)

    monkeypatch.setattr(analytics, "datetime", FrozenDateTime)
    assert analytics.wechat_today() == expected


@pytest.fixture
def client(monkeypatch):
    from app.routers import analytics

    monkeypatch.setattr(analytics, "wechat_today", lambda: date(2026, 11, 4))
    with TestClient(app) as client:
        yield client


def token_route(mock):
    return mock.post("/cgi-bin/stable_token").respond(
        200, json={"access_token": "VALID", "expires_in": 7200}
    )


@pytest.mark.parametrize("route,upstream,tool", ENDPOINTS)
@pytest.mark.parametrize("payload", [
    {"list": [{"msgid": "2247490098_1", "detail": {"share_user": 366}}], "is_delay": "false"},
    {"list": [], "is_delay": True},
    {"errcode": 48001, "errmsg": "api unauthorized"},
])
def test_analytics_forwards_dates_and_preserves_data(client, route, upstream, tool, payload):
    with respx.mock(base_url=BASE) as mock:
        token_route(mock)
        call = mock.post(f"/datacube/{upstream}").respond(200, json=payload)
        response = client.post(f"/wechat/analytics/{route}", json=DAY)
    assert response.status_code == 200
    assert response.json() == payload
    assert json.loads(call.calls.last.request.content) == DAY
    assert call.calls.last.request.url.params["access_token"] == "VALID"


@pytest.mark.parametrize("route,upstream,tool", ENDPOINTS)
@pytest.mark.parametrize("body", [
    {"begin_date": "2025-10-31", "end_date": "2025-10-31"},
    {"begin_date": "2026-11-04", "end_date": "2026-11-04"},
    {"begin_date": "2026-11-05", "end_date": "2026-11-05"},
    {"begin_date": "2026-11-02", "end_date": "2026-11-01"},
    {"begin_date": "2026-02-30", "end_date": "2026-02-30"},
    {"begin_date": "2026-1-01", "end_date": "2026-1-01"},
    {"begin_date": "2026-11-01T00:00:00", "end_date": "2026-11-01"},
    {"begin_date": 20261101, "end_date": "2026-11-01"},
    {"begin_date": "2026-11-01"},
    {**DAY, "article_id": "unsupported-filter"},
])
def test_invalid_dates_fail_before_any_upstream_request(client, route, upstream, tool, body):
    with respx.mock(base_url=BASE) as mock:
        response = client.post(f"/wechat/analytics/{route}", json=body)
        assert len(mock.calls) == 0
    assert response.status_code == 422


@pytest.mark.parametrize("route,upstream,tool", [e for e in ENDPOINTS if e[0] != "account-summary"])
def test_single_day_endpoints_reject_multi_day_range(client, route, upstream, tool):
    with respx.mock(base_url=BASE) as mock:
        response = client.post(f"/wechat/analytics/{route}", json={
            "begin_date": "2026-11-01", "end_date": "2026-11-02",
        })
        assert len(mock.calls) == 0
    assert response.status_code == 422


@pytest.mark.parametrize("begin,end", [
    ("2026-10-05", "2026-11-03"),  # 30 days inclusive, through yesterday
    ("2025-11-01", "2025-11-01"),  # first supported date
])
def test_account_summary_accepts_supported_boundaries(client, begin, end):
    with respx.mock(base_url=BASE) as mock:
        token_route(mock)
        mock.post("/datacube/getbizsummary").respond(200, json={"list": [], "is_delay": False})
        response = client.post("/wechat/analytics/account-summary", json={
            "begin_date": begin, "end_date": end,
        })
    assert response.status_code == 200


def test_account_summary_rejects_31_days(client):
    with respx.mock(base_url=BASE) as mock:
        response = client.post("/wechat/analytics/account-summary", json={
            "begin_date": "2026-10-04", "end_date": "2026-11-03",
        })
        assert len(mock.calls) == 0
    assert response.status_code == 422


def test_article_details_preserve_cumulative_rows_and_extended_fields(client):
    payload = {"list": [{
        "ref_date": "2025-11-01", "msgid": "10000050_1", "title": "测试文章",
        "content_url": "https://example.com/article", "publish_type": 1,
        "detail_list": [
            {"stat_date": "2025-11-01", "read_user": 12, "read_avg_activetime": 1.5},
            {"stat_date": "2025-11-02", "read_user": 20, "read_avg_activetime": 2.5},
        ],
    }], "is_delay": False}
    with respx.mock(base_url=BASE) as mock:
        token_route(mock)
        mock.post("/datacube/getarticletotaldetail").respond(200, json=payload)
        response = client.post("/wechat/analytics/article-details", json=DAY)
    assert response.json() == payload


def test_analytics_requires_the_configured_api_key(client, monkeypatch):
    monkeypatch.setattr(settings, "api_key", "test-only-key")
    with respx.mock(base_url=BASE) as mock:
        response = client.post("/wechat/analytics/article-read", json=DAY)
        assert len(mock.calls) == 0
    assert response.status_code == 401


@pytest.mark.parametrize("route,upstream,tool", ENDPOINTS + [
    ("freepublish/batchget", "/cgi-bin/freepublish/batchget", "freepublish_batchget"),
    ("freepublish/getarticle", "/cgi-bin/freepublish/getarticle", "freepublish_getarticle"),
])
async def test_read_tools_through_authenticated_mcp(monkeypatch, route, upstream, tool):
    api_key = "mcp-test-only-key"
    monkeypatch.setattr(settings, "api_key", api_key)
    arguments = {"article_id": "ARTICLE"} if tool == "freepublish_getarticle" else (
        {"offset": 0, "count": 20, "no_content": 1} if tool == "freepublish_batchget" else DAY
    )
    payload = {"list": [], "is_delay": "false"} if tool.startswith("analytics_") else {"item": []}
    request_info = HTTPRequestInfo(method="POST", path="/mcp",
        headers={settings.api_key_header.lower(): api_key}, cookies={}, query_params={}, body=None)
    upstream_path = upstream if upstream.startswith("/") else f"/datacube/{upstream}"
    with respx.mock(base_url=BASE) as mock:
        token_route(mock)
        call = mock.post(upstream_path).respond(200, json=payload)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as tool_client:
            content = await mcp._execute_api_tool(client=tool_client, tool_name=tool,
                arguments=arguments, operation_map=mcp.operation_map, http_request_info=request_info)
    assert json.loads(content[0].text) == payload
    assert json.loads(call.calls.last.request.content) == arguments
