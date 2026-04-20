"""发布能力 (freepublish) — publish drafts and query/delete published articles."""

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from ..wechat import wechat_client

router = APIRouter(prefix="/wechat/freepublish", tags=["wechat"])


class SubmitBody(BaseModel):
    media_id: str = Field(..., description="草稿的 media_id")


class PublishIdBody(BaseModel):
    publish_id: str = Field(..., description="发布任务的 publish_id")


class DeleteBody(BaseModel):
    model_config = ConfigDict(extra="allow")

    article_id: str = Field(..., description="成功发布时返回的 article_id")
    index: int = Field(0, description="要删除的文章在图文中的位置，1~N，0 表示全部")


class BatchGetBody(BaseModel):
    offset: int = Field(0, ge=0)
    count: int = Field(20, ge=1, le=20)
    no_content: int = Field(0, description="1 表示不返回 content，节省流量")


class ArticleIdBody(BaseModel):
    article_id: str = Field(..., description="成功发布时返回的 article_id")


@router.post("/submit", operation_id="freepublish_submit")
async def submit(body: SubmitBody) -> dict[str, Any]:
    """发布草稿 (/cgi-bin/freepublish/submit)."""
    return await wechat_client.call_json(
        "POST", "/cgi-bin/freepublish/submit", json=body.model_dump()
    )


@router.post("/get", operation_id="freepublish_get")
async def get_status(body: PublishIdBody) -> dict[str, Any]:
    """发布状态查询 (/cgi-bin/freepublish/get)."""
    return await wechat_client.call_json(
        "POST", "/cgi-bin/freepublish/get", json=body.model_dump()
    )


@router.post("/delete", operation_id="freepublish_delete")
async def delete(body: DeleteBody) -> dict[str, Any]:
    """删除发布 (/cgi-bin/freepublish/delete)."""
    return await wechat_client.call_json(
        "POST", "/cgi-bin/freepublish/delete", json=body.model_dump()
    )


@router.post("/batchget", operation_id="freepublish_batchget")
async def batchget(body: BatchGetBody) -> dict[str, Any]:
    """获取已发布的消息列表 (/cgi-bin/freepublish/batchget)."""
    return await wechat_client.call_json(
        "POST", "/cgi-bin/freepublish/batchget", json=body.model_dump()
    )


@router.post("/getarticle", operation_id="freepublish_getarticle")
async def getarticle(body: ArticleIdBody) -> dict[str, Any]:
    """获取已发布图文信息 (/cgi-bin/freepublish/getarticle)."""
    return await wechat_client.call_json(
        "POST", "/cgi-bin/freepublish/getarticle", json=body.model_dump()
    )
