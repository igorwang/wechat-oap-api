"""公众号关注状态的读写.

判据全部走库：进程重启不丢、多副本一致，且取关时不必再调 user/info
（那个接口在 subscribe=0 时不再返回 unionid）。
"""

from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .customer_service.models import WeChatFollower


class FollowerStore:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = session_factory

    async def is_follower(self, unionid: str | None) -> bool:
        if not unionid:
            return False
        async with self._sessions() as session:
            result = await session.execute(
                select(WeChatFollower.openid).where(
                    WeChatFollower.unionid == unionid,
                    WeChatFollower.subscribed.is_(True),
                )
            )
            return result.first() is not None

    async def mark_subscribed(self, openid: str, unionid: str | None) -> None:
        now = datetime.now(timezone.utc)
        async with self._sessions() as session:
            row = await session.get(WeChatFollower, openid)
            if row is None:
                row = WeChatFollower(openid=openid, subscribed_at=now)
                session.add(row)
            elif not row.subscribed:
                row.subscribed_at = now
            # 取关后重新关注时 user/info 又能给出 unionid 了，别用空值覆盖已存的
            if unionid:
                row.unionid = unionid
            row.subscribed = True
            await session.commit()

    async def mark_unsubscribed(self, openid: str) -> str | None:
        """按 openid 撤销关注状态，返回该用户的 unionid（未见过则 None）."""
        async with self._sessions() as session:
            row = await session.get(WeChatFollower, openid)
            if row is None:
                return None
            row.subscribed = False
            row.unsubscribed_at = datetime.now(timezone.utc)
            await session.commit()
            return row.unionid

    async def replace_all(self, pairs: list[tuple[str, str | None]]) -> int:
        """全量同步关注者名单：名单外的一律标记为已取关.

        用于冷启动兜底和纠偏——回调偶尔会丢，光靠事件会慢慢漂。
        """
        now = datetime.now(timezone.utc)
        async with self._sessions() as session:
            await session.execute(
                update(WeChatFollower)
                .where(WeChatFollower.subscribed.is_(True))
                .values(subscribed=False, unsubscribed_at=now)
            )
            for openid, unionid in pairs:
                row = await session.get(WeChatFollower, openid)
                if row is None:
                    row = WeChatFollower(openid=openid, subscribed_at=now)
                    session.add(row)
                if unionid:
                    row.unionid = unionid
                row.subscribed = True
                row.unsubscribed_at = None
            await session.commit()
            return len(pairs)
