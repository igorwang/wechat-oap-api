"""Persistent daily quota for customer messages handled by AI."""

from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import Date, Integer, String
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Mapped, mapped_column

from .models import Base

_BEIJING_TIME = timezone(timedelta(hours=8))


class _DailyCustomerQuota(Base):
    __tablename__ = "wechat_customer_daily_ai_quota"

    external_userid: Mapped[str] = mapped_column(String(128), primary_key=True)
    quota_date: Mapped[date] = mapped_column(Date, primary_key=True)
    used: Mapped[int] = mapped_column(Integer)


class CustomerQuotaStore:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._sessions = session_factory
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    async def try_consume(self, external_userid: str, *, limit: int = 50) -> bool:
        """Atomically reserve one AI message within today's allowance for this customer."""
        if not external_userid or limit < 1:
            return False
        quota_date = self._clock().astimezone(_BEIJING_TIME).date()
        async with self._sessions.begin() as session:
            insert = sqlite_insert if session.get_bind().dialect.name == "sqlite" else postgres_insert
            statement = (
                insert(_DailyCustomerQuota)
                .values(external_userid=external_userid, quota_date=quota_date, used=1)
                .on_conflict_do_update(
                    index_elements=[_DailyCustomerQuota.external_userid, _DailyCustomerQuota.quota_date],
                    set_={"used": _DailyCustomerQuota.used + 1},
                    where=_DailyCustomerQuota.used < limit,
                )
                .returning(_DailyCustomerQuota.used)
            )
            result = await session.execute(statement)
            return result.scalar_one_or_none() is not None
