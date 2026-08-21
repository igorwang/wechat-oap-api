"""CustomerStore — 微信客服客户信息落库.

external_userid 只对 48 小时内互动过的客户有效，因此必须在会话发生时落库，
事后无法补查。测试跑在内存 SQLite 上；生产用 PostgreSQL。
"""

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.customer_service.models import Base
from app.customer_service.store import CustomerStore


@pytest.fixture
async def store():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield CustomerStore(async_sessionmaker(engine, expire_on_commit=False))
    await engine.dispose()


async def test_upsert_inserts_new_customer(store):
    await store.upsert(
        {
            "external_userid": "wm_user_1",
            "nickname": "IGOR.gpt",
            "avatar": "http://wx.qlogo.cn/x",
            "gender": 1,
            "unionid": None,
        },
        open_kfid="wk_1",
        scene="test",
    )
    got = await store.get("wm_user_1")
    assert got.external_userid == "wm_user_1"
    assert got.nickname == "IGOR.gpt"
    assert got.gender == 1
    assert got.unionid is None
    assert got.open_kfid == "wk_1"
    assert got.scene == "test"
    assert got.first_seen_at is not None
    assert got.last_seen_at is not None


async def test_upsert_updates_existing_and_keeps_first_seen(store):
    await store.upsert({"external_userid": "wm_user_1", "nickname": "旧名字"})
    first = await store.get("wm_user_1")

    await store.upsert({"external_userid": "wm_user_1", "nickname": "新名字"})
    second = await store.get("wm_user_1")

    assert second.nickname == "新名字"
    assert second.first_seen_at == first.first_seen_at, "首次见到时间不应被覆盖"
    assert second.last_seen_at >= first.last_seen_at


async def test_upsert_backfills_unionid_without_erasing_it(store):
    """绑定公众号前 unionid 为空；绑定后能补上，且之后的空值不能把它抹掉."""
    await store.upsert({"external_userid": "wm_user_1", "unionid": None})
    assert (await store.get("wm_user_1")).unionid is None

    await store.upsert({"external_userid": "wm_user_1", "unionid": "o_union_abc"})
    assert (await store.get("wm_user_1")).unionid == "o_union_abc"

    # 后续接口又没返回 unionid（未绑定/第三方应用），已存的值必须保留
    await store.upsert({"external_userid": "wm_user_1", "unionid": None})
    assert (await store.get("wm_user_1")).unionid == "o_union_abc"


async def test_get_returns_none_for_unknown(store):
    assert await store.get("nobody") is None


async def test_find_by_unionid(store):
    await store.upsert({"external_userid": "wm_user_1", "unionid": "o_union_abc"})
    found = await store.find_by_unionid("o_union_abc")
    assert found.external_userid == "wm_user_1"
    assert await store.find_by_unionid("o_missing") is None
