"""公众号关注者名单——客服门禁的判据来源.

为什么不能用客服侧的 unionid 判断关注：企业微信绑定开放平台后，客户只要
发起一次客服会话就会被分配 unionid，从没关注过的号也有；而且取关不回收。
实测 5 个客户（含 1 个从未关注、1 个已取关）全部有 unionid，判据完全失效。

真实关注状态只能从公众号侧取：/cgi-bin/user/get 只列出**当前**关注者，
取关的人会从名单里消失。
"""

import asyncio
import logging
import time

from .wechat import WeChatClient, wechat_client

logger = logging.getLogger(__name__)

# user/info/batchget 单次上限 100
_BATCH_SIZE = 100
# user/get 单页上限 10000；设个页数上限兜底，避免异常响应导致死循环
_MAX_PAGES = 50


class FollowerDirectory:
    """缓存公众号关注者的 unionid 集合。

    整份名单按 ttl 过期。问到一个不在名单里的 unionid 时，如果距上次拉取
    已超过 refresh_on_miss_after 秒就重拉一次——否则刚关注完的人会被上一轮
    的旧名单挡住，而这恰恰是引导关注后最常见的一步。
    """

    def __init__(
        self,
        client: WeChatClient | None = None,
        *,
        ttl: float = 300.0,
        refresh_on_miss_after: float = 30.0,
    ) -> None:
        self._client = client or wechat_client
        self._ttl = ttl
        self._refresh_on_miss_after = refresh_on_miss_after
        self._unionids: set[str] = set()
        self._fetched_at = 0.0
        self._lock = asyncio.Lock()

    async def _fetch(self) -> set[str]:
        """分页拉全量关注者，换回 unionid 集合."""
        openids: list[str] = []
        cursor = ""
        for _ in range(_MAX_PAGES):
            data = await self._client.call_json(
                "GET", "/cgi-bin/user/get", params={"next_openid": cursor}
            )
            if data.get("errcode"):
                raise RuntimeError(f"user/get failed: {data}")
            page = (data.get("data") or {}).get("openid") or []
            openids.extend(page)
            cursor = data.get("next_openid") or ""
            if not page or not cursor:
                break
        else:
            logger.warning("user/get 达到 %d 页上限，关注者名单可能不完整", _MAX_PAGES)

        unionids: set[str] = set()
        for start in range(0, len(openids), _BATCH_SIZE):
            chunk = openids[start : start + _BATCH_SIZE]
            data = await self._client.call_json(
                "POST",
                "/cgi-bin/user/info/batchget",
                json={"user_list": [{"openid": o, "lang": "zh_CN"} for o in chunk]},
            )
            if data.get("errcode"):
                raise RuntimeError(f"user/info/batchget failed: {data}")
            for info in data.get("user_info_list") or []:
                # subscribe=0 是已取关；无 unionid 说明公众号没绑开放平台
                if info.get("subscribe") == 1 and info.get("unionid"):
                    unionids.add(info["unionid"])
        logger.info("公众号关注者 %d 人，其中 %d 人有 unionid", len(openids), len(unionids))
        return unionids

    async def _refresh(self) -> None:
        async with self._lock:
            fetched = await self._fetch()
            self._unionids = fetched
            self._fetched_at = time.monotonic()

    async def unionids(self) -> set[str]:
        if time.monotonic() - self._fetched_at >= self._ttl:
            await self._refresh()
        return self._unionids

    async def record_subscribe(self, openid: str) -> str | None:
        """收到 subscribe 回调：用 openid 换 unionid 并立刻记进名单.

        事件驱动是这份名单的主要维护方式，全量拉取只用于冷启动兜底。
        """
        unionid = await self._unionid_of(openid)
        if unionid:
            self._unionids.add(unionid)
        return unionid

    async def record_unsubscribe(self, openid: str) -> str | None:
        """收到 unsubscribe 回调：立刻从名单里去掉，不必等 TTL 过期."""
        unionid = await self._unionid_of(openid)
        if unionid:
            self._unionids.discard(unionid)
        return unionid

    async def _unionid_of(self, openid: str) -> str | None:
        """openid → unionid。取关后 user/info 仍会返回 unionid，只是 subscribe=0."""
        if not openid:
            return None
        data = await self._client.call_json(
            "GET", "/cgi-bin/user/info", params={"openid": openid, "lang": "zh_CN"}
        )
        if data.get("errcode"):
            raise RuntimeError(f"user/info failed: {data}")
        return data.get("unionid") or None

    async def is_follower(self, unionid: str | None) -> bool:
        if not unionid:
            return False
        known = await self.unionids()
        if unionid in known:
            return True
        if time.monotonic() - self._fetched_at >= self._refresh_on_miss_after:
            await self._refresh()
        return unionid in self._unionids


follower_directory = FollowerDirectory()
