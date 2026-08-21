"""客户信息读写."""

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .models import WeChatCustomer

# 接口未返回这些字段时不要覆盖已存的值（例如第三方应用拿不到 avatar/unionid）
_PRESERVE_IF_MISSING = ("unionid", "nickname", "avatar", "gender")


class CustomerStore:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = session_factory

    async def get(self, external_userid: str) -> WeChatCustomer | None:
        async with self._sessions() as session:
            return await session.get(WeChatCustomer, external_userid)

    async def find_by_unionid(self, unionid: str) -> WeChatCustomer | None:
        async with self._sessions() as session:
            result = await session.execute(
                select(WeChatCustomer).where(WeChatCustomer.unionid == unionid)
            )
            return result.scalar_one_or_none()

    async def upsert(
        self,
        customer: dict[str, Any],
        *,
        open_kfid: str | None = None,
        scene: str | None = None,
        scene_param: str | None = None,
        bump_message_count: bool = False,
    ) -> WeChatCustomer:
        """按 external_userid 落库；已存在则更新，并保留首次见到时间."""
        external_userid = customer["external_userid"]
        async with self._sessions() as session:
            row = await session.get(WeChatCustomer, external_userid)
            if row is None:
                row = WeChatCustomer(external_userid=external_userid)
                session.add(row)

            for field in _PRESERVE_IF_MISSING:
                value = customer.get(field)
                if value not in (None, ""):
                    setattr(row, field, value)

            if open_kfid:
                row.open_kfid = open_kfid
            if scene:
                row.scene = scene
            if scene_param:
                row.scene_param = scene_param
            if bump_message_count:
                row.message_count = (row.message_count or 0) + 1

            row.raw = customer
            row.last_seen_at = datetime.now(timezone.utc)

            await session.commit()
            await session.refresh(row)
            return row
