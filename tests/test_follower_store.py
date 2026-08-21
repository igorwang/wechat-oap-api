"""FollowerStore — 公众号关注状态落库.

取关时微信只给 openid（user/info 在 subscribe=0 时不再返回 unionid），所以
openid → unionid 的对应关系必须在关注时就存下来，取关时按 openid 反查。
"""

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.customer_service.models import Base
from app.follower_store import FollowerStore


@pytest.fixture
async def store():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield FollowerStore(async_sessionmaker(engine, expire_on_commit=False))
    await engine.dispose()


async def test_subscribed_user_is_a_follower(store):
    await store.mark_subscribed("o1", "u1")
    assert await store.is_follower("u1") is True


async def test_unknown_unionid_is_not_a_follower(store):
    assert await store.is_follower("u_never_seen") is False


async def test_unsubscribe_by_openid_alone(store):
    """取关回调只带 openid——必须能仅凭 openid 撤销关注状态."""
    await store.mark_subscribed("o1", "u1")

    unionid = await store.mark_unsubscribed("o1")

    assert unionid == "u1"
    assert await store.is_follower("u1") is False


async def test_unsubscribe_of_unknown_openid_is_harmless(store):
    assert await store.mark_unsubscribed("o_never_seen") is None


async def test_resubscribe_flips_status_back(store):
    await store.mark_subscribed("o1", "u1")
    await store.mark_unsubscribed("o1")

    await store.mark_subscribed("o1", "u1")

    assert await store.is_follower("u1") is True


async def test_bulk_replace_seeds_the_table_and_drops_missing(store):
    """全量同步：名单里没有的人视为已取关，而不是留着旧状态."""
    await store.mark_subscribed("o_gone", "u_gone")

    await store.replace_all([("o1", "u1"), ("o2", "u2")])

    assert await store.is_follower("u1") is True
    assert await store.is_follower("u2") is True
    assert await store.is_follower("u_gone") is False


async def test_empty_unionid_is_never_a_follower(store):
    assert await store.is_follower("") is False
    assert await store.is_follower(None) is False
