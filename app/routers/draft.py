"""草稿管理与商品卡片 (draft + product card)."""

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from ..wechat import wechat_client

router = APIRouter(prefix="/wechat/draft", tags=["wechat"])


class Article(BaseModel):
    """单篇图文。扩展字段通过 extra='allow' 透传给微信。"""

    model_config = ConfigDict(extra="allow")

    title: str
    author: str | None = None
    digest: str | None = None
    content: str
    content_source_url: str | None = None
    thumb_media_id: str
    show_cover_pic: int | None = 0
    need_open_comment: int | None = 0
    only_fans_can_comment: int | None = 0


class AddBody(BaseModel):
    articles: list[Article] = Field(..., min_length=1)


class MediaIdBody(BaseModel):
    media_id: str


class UpdateBody(BaseModel):
    media_id: str
    index: int = Field(..., ge=0, description="要更新的文章在图文中的位置，从 0 开始")
    articles: Article


class BatchGetBody(BaseModel):
    offset: int = Field(0, ge=0)
    count: int = Field(20, ge=1, le=20)
    no_content: int = Field(0)


class SwitchQuery(BaseModel):
    checkonly: int = Field(
        1, description="1 仅检查状态 / 0 正式开启（开启后无法关闭）"
    )


@router.post("/add", operation_id="draft_add")
async def add(body: AddBody) -> dict[str, Any]:
    """新增草稿 (/cgi-bin/draft/add)."""
    return await wechat_client.call_json(
        "POST", "/cgi-bin/draft/add", json=body.model_dump(exclude_none=True)
    )


@router.post("/update", operation_id="draft_update")
async def update(body: UpdateBody) -> dict[str, Any]:
    """更新草稿 (/cgi-bin/draft/update)."""
    return await wechat_client.call_json(
        "POST", "/cgi-bin/draft/update", json=body.model_dump(exclude_none=True)
    )


@router.post("/get", operation_id="draft_get")
async def get_draft(body: MediaIdBody) -> dict[str, Any]:
    """获取草稿详情 (/cgi-bin/draft/get)."""
    return await wechat_client.call_json(
        "POST", "/cgi-bin/draft/get", json=body.model_dump()
    )


@router.post("/batchget", operation_id="draft_batchget")
async def batchget(body: BatchGetBody) -> dict[str, Any]:
    """获取草稿列表 (/cgi-bin/draft/batchget)."""
    return await wechat_client.call_json(
        "POST", "/cgi-bin/draft/batchget", json=body.model_dump()
    )


@router.get("/count", operation_id="draft_count")
async def count() -> dict[str, Any]:
    """获取草稿总数 (/cgi-bin/draft/count)."""
    return await wechat_client.call_json("GET", "/cgi-bin/draft/count")


@router.post("/delete", operation_id="draft_delete")
async def delete(body: MediaIdBody) -> dict[str, Any]:
    """删除草稿 (/cgi-bin/draft/delete)."""
    return await wechat_client.call_json(
        "POST", "/cgi-bin/draft/delete", json=body.model_dump()
    )


@router.post("/switch", operation_id="draft_switch")
async def switch(q: SwitchQuery) -> dict[str, Any]:
    """草稿箱开关 (/cgi-bin/draft/switch)."""
    return await wechat_client.call_json(
        "POST", "/cgi-bin/draft/switch", params={"checkonly": q.checkonly}
    )


class ProductCardBody(BaseModel):
    url: str = Field(..., description="视频号小店商品链接")


@router.post(
    "/product-cardinfo",
    operation_id="draft_product_cardinfo",
    tags=["wechat"],
)
async def product_cardinfo(body: ProductCardBody) -> dict[str, Any]:
    """获取商品卡片的 DOM 结构 (/channels/ec/service/product/getcardinfo)."""
    return await wechat_client.call_json(
        "POST",
        "/channels/ec/service/product/getcardinfo",
        json=body.model_dump(),
    )
