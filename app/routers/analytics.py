"""Read-only article operations using the current WeChat datacube APIs."""

from datetime import date, datetime, timedelta, timezone
from typing import Any, ClassVar, Self

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..wechat import wechat_client

router = APIRouter(prefix="/wechat/analytics", tags=["wechat", "analytics"])


def wechat_today() -> date:
    """WeChat's reporting day uses Beijing time, independent of server timezone."""
    return datetime.now(timezone(timedelta(hours=8))).date()


class DateRangeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_days: ClassVar[int] = 30
    begin_date: str = Field(
        ..., pattern=r"^\d{4}-\d{2}-\d{2}$",
        description="YYYY-MM-DD，含当天；最早 2025-11-01。单篇详情用发表日期，其余用统计日期。",
    )
    end_date: str = Field(
        ..., pattern=r"^\d{4}-\d{2}-\d{2}$",
        description="YYYY-MM-DD，含当天；最晚北京时间昨日。概况最多 30 天，其余起止必须相同。",
    )

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        begin = date.fromisoformat(self.begin_date)
        end = date.fromisoformat(self.end_date)
        if begin < date(2025, 11, 1):
            raise ValueError("begin_date must be on or after 2025-11-01")
        if end < begin:
            raise ValueError("end_date must be on or after begin_date")
        if end >= wechat_today():
            raise ValueError("end_date must be no later than yesterday in Asia/Shanghai")
        if (end - begin).days + 1 > self.max_days:
            raise ValueError(f"date range must not exceed {self.max_days} day(s), inclusive")
        return self


class SingleDayBody(DateRangeBody):
    max_days: ClassVar[int] = 1


@router.post("/article-read", operation_id="analytics_article_read")
async def article_read(body: SingleDayBody) -> dict[str, Any]:
    """按单个统计日期获取每篇文章的阅读人数及来源（起止相同，非实时）。

    对应 /datacube/getarticleread。仅企业主体已认证账号；建议次日 8 点后查询。
    read_user 是人数。原样保留 list、is_delay 和微信权限错误；空列表不代表零阅读。
    """
    return await wechat_client.call_json(
        "POST", "/datacube/getarticleread", json=body.model_dump()
    )


@router.post("/article-share", operation_id="analytics_article_share")
async def article_share(body: SingleDayBody) -> dict[str, Any]:
    """按单个统计日期获取每篇文章的分享人数（起止相同，非分享次数）。

    对应 /datacube/getarticleshare。仅企业主体已认证账号；建议次日 8 点后查询。
    原样保留微信响应；is_delay 可能是布尔值或字符串，空列表不代表零分享。
    """
    return await wechat_client.call_json(
        "POST", "/datacube/getarticleshare", json=body.model_dump()
    )


@router.post("/account-summary", operation_id="analytics_account_summary")
async def account_summary(body: DateRangeBody) -> dict[str, Any]:
    """获取账号每天的文章运营概况，统计日期区间含首尾，最多 30 天。

    对应 /datacube/getbizsummary。仅企业主体已认证账号；最晚昨日，建议次日 8 点后查询。
    包含阅读来源、分享、赞、留言、收藏等官方原始字段。每天人数不能相加当作区间去重人数。
    原样保留延迟标记、空数据及权限错误。
    """
    return await wechat_client.call_json(
        "POST", "/datacube/getbizsummary", json=body.model_dump()
    )


@router.post("/article-details", operation_id="analytics_article_details")
async def article_details(body: SingleDayBody) -> dict[str, Any]:
    """获取某个发表日期的全部文章详情（起止相同，按发表日期而非统计日期查询）。

    对应 /datacube/getarticletotaldetail。仅企业主体已认证账号；含通知及未通知的已发表内容。
    返回标题、链接、阅读质量等；单篇只跟踪发表起 30 天。detail_list 各 stat_date 的指标
    是发表日至该日的累计，不可相加。msgid 不是草稿 media_id 或发布 article_id。
    原样保留微信响应、延迟标记及权限错误；不是抓取任意文章 URL 的接口。
    """
    return await wechat_client.call_json(
        "POST", "/datacube/getarticletotaldetail", json=body.model_dump()
    )
