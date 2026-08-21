"""FollowerDirectory — 用公众号接口判断客户当前是否关注.

微信客服侧的 unionid 判断不了关注状态（企业微信绑定开放平台后，客户只要
发起会话就会拿到 unionid，取关也不回收），只能从公众号侧取真实关注者名单。
"""

import httpx
import pytest
import respx

from app.followers import FollowerDirectory

API = "https://api.weixin.qq.com"


@pytest.fixture
def wechat(monkeypatch):
    from app.wechat import WeChatClient
    from app.config import settings

    monkeypatch.setattr(settings, "wechat_appid", "appid1")
    monkeypatch.setattr(settings, "wechat_appsecret", "secret1")
    monkeypatch.setattr(settings, "wechat_token_cache_path", "")
    return WeChatClient(cache_path="")


def _mock_token(mock):
    return mock.get("/cgi-bin/token").mock(
        return_value=httpx.Response(200, json={"access_token": "OATOK", "expires_in": 7200})
    )


def _mock_user_get(mock, pages):
    return mock.get("/cgi-bin/user/get").mock(
        side_effect=[httpx.Response(200, json=p) for p in pages]
    )


def _mock_batchget(mock, pages):
    return mock.post("/cgi-bin/user/info/batchget").mock(
        side_effect=[httpx.Response(200, json=p) for p in pages]
    )


async def test_collects_unionids_across_pages(wechat):
    async with respx.mock(base_url=API) as mock:
        _mock_token(mock)
        _mock_user_get(mock, [
            {"total": 3, "count": 2, "data": {"openid": ["o1", "o2"]}, "next_openid": "o2"},
            {"total": 3, "count": 1, "data": {"openid": ["o3"]}, "next_openid": "o3"},
            {"total": 3, "count": 0, "data": {}, "next_openid": ""},
        ])
        # 3 个 openid 不足 100，合并成一次 batchget
        _mock_batchget(mock, [
            {"user_info_list": [
                {"subscribe": 1, "openid": "o1", "unionid": "u1"},
                {"subscribe": 1, "openid": "o2", "unionid": "u2"},
                {"subscribe": 1, "openid": "o3", "unionid": "u3"},
            ]},
        ])

        directory = FollowerDirectory(wechat)
        assert await directory.unionids() == {"u1", "u2", "u3"}


async def test_batchget_is_chunked_at_100(wechat):
    """user/info/batchget 单次上限 100，超出必须分批."""
    openids = [f"o{i}" for i in range(250)]
    async with respx.mock(base_url=API) as mock:
        _mock_token(mock)
        _mock_user_get(mock, [
            {"count": 250, "data": {"openid": openids}, "next_openid": "o249"},
            {"count": 0, "data": {}, "next_openid": ""},
        ])
        route = _mock_batchget(mock, [
            {"user_info_list": [
                {"subscribe": 1, "openid": o, "unionid": f"u{o}"} for o in openids[s : s + 100]
            ]}
            for s in (0, 100, 200)
        ])

        found = await FollowerDirectory(wechat).unionids()

        assert route.call_count == 3
        assert len(found) == 250


async def test_skips_unsubscribed_and_unionid_less_entries(wechat):
    async with respx.mock(base_url=API) as mock:
        _mock_token(mock)
        _mock_user_get(mock, [
            {"count": 3, "data": {"openid": ["o1", "o2", "o3"]}, "next_openid": "o3"},
            {"count": 0, "data": {}, "next_openid": ""},
        ])
        _mock_batchget(mock, [
            {"user_info_list": [
                {"subscribe": 1, "openid": "o1", "unionid": "u1"},
                {"subscribe": 0, "openid": "o2", "unionid": "u2"},   # 已取关
                {"subscribe": 1, "openid": "o3"},                     # 未绑开放平台
            ]},
        ])

        assert await FollowerDirectory(wechat).unionids() == {"u1"}


async def test_result_is_cached_within_ttl(wechat):
    async with respx.mock(base_url=API) as mock:
        _mock_token(mock)
        route = _mock_user_get(mock, [
            {"count": 1, "data": {"openid": ["o1"]}, "next_openid": "o1"},
            {"count": 0, "data": {}, "next_openid": ""},
        ])
        _mock_batchget(mock, [{"user_info_list": [{"subscribe": 1, "openid": "o1", "unionid": "u1"}]}])

        directory = FollowerDirectory(wechat, ttl=300)
        assert await directory.is_follower("u1") is True
        assert await directory.is_follower("u1") is True
        assert route.call_count == 2  # 只拉了一轮（两页），第二次问走缓存


async def test_miss_triggers_refresh_so_a_new_follower_passes(wechat):
    """刚关注的人不该被缓存挡在门外：命中不了就重拉一次名单再判."""
    async with respx.mock(base_url=API) as mock:
        _mock_token(mock)
        _mock_user_get(mock, [
            {"count": 0, "data": {}, "next_openid": ""},                       # 第一轮：无关注者
            {"count": 1, "data": {"openid": ["o9"]}, "next_openid": "o9"},     # 第二轮：他关注了
            {"count": 0, "data": {}, "next_openid": ""},
        ])
        _mock_batchget(mock, [{"user_info_list": [{"subscribe": 1, "openid": "o9", "unionid": "u9"}]}])

        directory = FollowerDirectory(wechat, ttl=300, refresh_on_miss_after=0)
        assert await directory.is_follower("u9") is True


async def test_empty_unionid_is_never_a_follower(wechat):
    """客服侧偶尔取不到 unionid，空值不能当成命中."""
    directory = FollowerDirectory(wechat)
    assert await directory.is_follower("") is False
    assert await directory.is_follower(None) is False


# ---- 启动播种 ----


async def test_bootstrap_seeds_the_directory(wechat):
    async with respx.mock(base_url=API) as mock:
        _mock_token(mock)
        _mock_user_get(mock, [
            {"count": 2, "data": {"openid": ["o1", "o2"]}, "next_openid": "o2"},
            {"count": 0, "data": {}, "next_openid": ""},
        ])
        _mock_batchget(mock, [{"user_info_list": [
            {"subscribe": 1, "openid": "o1", "unionid": "u1"},
            {"subscribe": 1, "openid": "o2", "unionid": "u2"},
        ]}])

        directory = FollowerDirectory(wechat)
        assert await directory.bootstrap() == 2
        assert await directory.is_follower("u1") is True


async def test_bootstrap_never_raises_when_the_api_fails(wechat):
    """公众号 IP 白名单没配好之类的问题不该让服务起不来."""
    async with respx.mock(base_url=API) as mock:
        _mock_token(mock)
        mock.get("/cgi-bin/user/get").mock(
            return_value=httpx.Response(200, json={"errcode": 40164, "errmsg": "invalid ip"})
        )

        assert await FollowerDirectory(wechat).bootstrap() == 0


async def test_bootstrap_gives_up_instead_of_hanging_startup(wechat, monkeypatch):
    """粉丝多时全量同步可能很久，不能把启动卡死."""
    import asyncio

    async def never_finishes():
        await asyncio.sleep(60)

    directory = FollowerDirectory(wechat)
    monkeypatch.setattr(directory, "_refresh", never_finishes)

    assert await directory.bootstrap(timeout=0.05) == 0
