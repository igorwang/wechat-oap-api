"""公众号关注者名单——客服门禁的判据来源.

为什么不能用客服侧的 unionid 判断关注：企业微信绑定开放平台后，客户只要
发起一次客服会话就会被分配 unionid，从没关注过的号也有；而且取关不回收。
实测 5 个客户（含 1 个从未关注、1 个已取关）全部有 unionid，判据完全失效。

真实关注状态只能从公众号侧取，且以事件为主、全量拉取为辅：
  subscribe / unsubscribe 回调  →  实时更新（主）
  user/get + user/info/batchget →  冷启动播种、定期纠偏（辅，回调会丢）

配了 DATABASE_URL 时状态落库（重启不丢、多副本一致）；没配则退化成进程内
集合，功能一样只是不持久。
"""

import asyncio
import logging
import time

from .follower_store import FollowerStore
from .wechat import WeChatClient, wechat_client

logger = logging.getLogger(__name__)

# user/info/batchget 单次上限 100
_BATCH_SIZE = 100
# user/get 单页上限 10000；设个页数上限兜底，避免异常响应导致死循环
_MAX_PAGES = 50


class FollowerDirectory:
    """判断某个 unionid 当前是否关注了公众号.

    ttl 是全量纠偏的间隔，不是判据的主要来源——关注/取关靠回调实时生效。
    问到一个不在名单里的 unionid 时，如果距上次拉取已超过 refresh_on_miss_after
    秒就重拉一次，避免刚关注完的人被旧名单挡住（回调万一没到）。
    """

    def __init__(
        self,
        client: WeChatClient | None = None,
        *,
        store: FollowerStore | None = None,
        ttl: float = 300.0,
        refresh_on_miss_after: float = 30.0,
    ) -> None:
        self._client = client or wechat_client
        self.store = store
        self._ttl = ttl
        self._refresh_on_miss_after = refresh_on_miss_after
        self._unionids: set[str] = set()
        self._fetched_at = 0.0
        self._lock = asyncio.Lock()

    # ---------------- 全量拉取（冷启动 / 纠偏） ----------------

    async def _fetch(self) -> list[tuple[str, str | None]]:
        """分页拉全量关注者，返回 (openid, unionid) 对.

        openid 也要留着：取关回调只带 openid，而 user/info 在 subscribe=0 时
        不再返回 unionid，没有这层映射就撤销不了关注状态。
        """
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

        pairs: list[tuple[str, str | None]] = []
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
                    pairs.append((info["openid"], info["unionid"]))
        logger.info("公众号关注者 %d 人，其中 %d 人有 unionid", len(openids), len(pairs))
        return pairs

    async def _refresh(self) -> None:
        async with self._lock:
            pairs = await self._fetch()
            self._unionids = {u for _, u in pairs if u}
            self._fetched_at = time.monotonic()
            if self.store:
                await self.store.replace_all(pairs)

    async def bootstrap(self, timeout: float = 30.0) -> int:
        """启动时播种关注者名单，返回已关注人数.

        不播种的话，库是空的，第一个发消息的老粉丝会被误拦一次（要等门禁落空
        触发的那次纠偏跑完才恢复）。

        失败或超时都只记日志不抛：公众号凭证/IP 白名单没配好不该让服务起不来，
        大不了退回按需纠偏。
        """
        try:
            await asyncio.wait_for(self._refresh(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning("关注者名单同步超时（>%ss），改为按需纠偏", timeout)
            return 0
        except Exception:
            logger.exception("关注者名单同步失败，改为按需纠偏")
            return 0
        logger.info("关注者名单已同步：%d 人", len(self._unionids))
        return len(self._unionids)

    async def _refresh_if_stale(self, older_than: float) -> None:
        if time.monotonic() - self._fetched_at >= older_than:
            await self._refresh()

    async def unionids(self) -> set[str]:
        """进程内的关注者 unionid 集合（未配库时的判据）."""
        await self._refresh_if_stale(self._ttl)
        return self._unionids

    # ---------------- 回调事件（主要维护方式） ----------------

    async def record_subscribe(self, openid: str) -> str | None:
        """收到 subscribe 回调：用 openid 换 unionid 并立刻记进名单."""
        unionid = await self._unionid_of(openid)
        if unionid:
            self._unionids.add(unionid)
        if self.store:
            await self.store.mark_subscribed(openid, unionid)
        return unionid

    async def record_unsubscribe(self, openid: str) -> str | None:
        """收到 unsubscribe 回调：立刻撤销关注状态.

        这里不调 user/info——取关后它只返回 openid，拿不到 unionid。库里存着
        关注时记下的映射，按 openid 反查即可。没配库时只能退回去问接口，拿不到
        就等 ttl 纠偏。
        """
        if self.store:
            unionid = await self.store.mark_unsubscribed(openid)
        else:
            unionid = await self._unionid_of(openid)
        if unionid:
            self._unionids.discard(unionid)
        return unionid

    async def _unionid_of(self, openid: str) -> str | None:
        if not openid:
            return None
        data = await self._client.call_json(
            "GET", "/cgi-bin/user/info", params={"openid": openid, "lang": "zh_CN"}
        )
        if data.get("errcode"):
            raise RuntimeError(f"user/info failed: {data}")
        return data.get("unionid") or None

    # ---------------- 判据 ----------------

    async def is_follower(self, unionid: str | None) -> bool:
        if not unionid:
            return False
        if self.store:
            if await self.store.is_follower(unionid):
                return True
            # 没命中可能是回调丢了或库还没播种，纠偏一次再判
            await self._refresh_if_stale(self._refresh_on_miss_after)
            return await self.store.is_follower(unionid)
        if unionid in await self.unionids():
            return True
        await self._refresh_if_stale(self._refresh_on_miss_after)
        return unionid in self._unionids


follower_directory = FollowerDirectory()
