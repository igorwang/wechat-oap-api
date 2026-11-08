"""Daily WeChat customer quotas are shared by all workers and reset at UTC+8 midnight."""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.customer_service.models import Base
from app.customer_service.quota import CustomerQuotaStore


@pytest.fixture
async def quota_sessions(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'quota.db'}")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


async def test_fiftieth_message_is_allowed_and_next_is_rejected(quota_sessions):
    now = datetime(2026, 11, 8, 8, 0, tzinfo=timezone.utc)
    quota = CustomerQuotaStore(quota_sessions, clock=lambda: now)
    for _ in range(50):
        assert await quota.try_consume("wx_user_a")

    # New worker/instance still sees the same limit.
    other_worker = CustomerQuotaStore(quota_sessions, clock=lambda: now)
    assert not await other_worker.try_consume("wx_user_a")
    assert await other_worker.try_consume("wx_user_b")


async def test_quota_resets_at_beijing_midnight(quota_sessions):
    now = datetime(2026, 11, 8, 15, 59, 59, tzinfo=timezone.utc)
    quota = CustomerQuotaStore(quota_sessions, clock=lambda: now)
    assert await quota.try_consume("wx_user", limit=1)
    assert not await quota.try_consume("wx_user", limit=1)

    now += timedelta(seconds=1)
    assert await quota.try_consume("wx_user", limit=1)
    assert not await quota.try_consume("wx_user", limit=1)


async def test_parallel_attempts_do_not_overrun_the_cap(quota_sessions):
    now = datetime(2026, 11, 8, 8, 0, tzinfo=timezone.utc)
    workers = [CustomerQuotaStore(quota_sessions, clock=lambda: now) for _ in range(2)]
    results = await asyncio.gather(
        *(workers[index % 2].try_consume("wx_user", limit=4) for index in range(12))
    )

    assert results.count(True) == 4
    assert results.count(False) == 8
