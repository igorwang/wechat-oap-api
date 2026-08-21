"""数据库连接与建表.

未配置 DATABASE_URL 时整个持久化层关闭，机器人仍可正常收发消息——
落库是增强，不是收发消息的前置条件。
"""

import logging

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from .config import settings
from .customer_service.models import Base

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, url: str) -> None:
        self._engine: AsyncEngine = create_async_engine(url, pool_pre_ping=True)
        self.sessions = async_sessionmaker(self._engine, expire_on_commit=False)

    async def create_all(self) -> None:
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def close(self) -> None:
        await self._engine.dispose()


async def init_database() -> Database | None:
    """按配置初始化数据库；未配置或连接失败时返回 None 并降级为不落库."""
    if not settings.database_url:
        logger.info("DATABASE_URL not set — customer persistence disabled")
        return None
    db = Database(settings.database_url)
    try:
        await db.create_all()
    except Exception:
        logger.exception("database init failed — continuing without persistence")
        await db.close()
        return None
    logger.info("database ready")
    return db
