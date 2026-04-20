"""基础消息 — 群发 / 一次性订阅 / 自动回复."""

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from ..wechat import wechat_client

router = APIRouter(prefix="/wechat/message", tags=["wechat"])


# -------- 群发 (mass) --------


class MassDeleteBody(BaseModel):
    msg_id: int = Field(..., description="要删除的群发消息 ID")
    article_idx: int = Field(
        0, description="删除图文消息中具体某篇，从 1 开始；0 表示全部"
    )


class MassGetBody(BaseModel):
    msg_id: str


class MassSpeedBody(BaseModel):
    speed: int = Field(..., ge=0, le=4, description="0~4，值越小越快")


class MassPreviewBody(BaseModel):
    """预览消息。支持按 openid (touser) 或微信号 (towxname)，至少一个必填。"""

    model_config = ConfigDict(extra="allow")

    touser: str | None = None
    towxname: str | None = None
    msgtype: str = Field(..., description="mpnews | text | voice | music | image | mpvideo | wxcard")


class MassSendAllBody(BaseModel):
    model_config = ConfigDict(extra="allow")

    filter: dict[str, Any] = Field(..., description="{'is_to_all': bool, 'tag_id': int}")
    msgtype: str


class UploadNewsBody(BaseModel):
    """上传图文素材 — 群发专用。"""

    model_config = ConfigDict(extra="allow")

    articles: list[dict[str, Any]] = Field(..., min_length=1)


@router.post("/mass/delete", operation_id="message_mass_delete")
async def mass_delete(body: MassDeleteBody) -> dict[str, Any]:
    """删除群发消息 (/cgi-bin/message/mass/delete)."""
    return await wechat_client.call_json(
        "POST", "/cgi-bin/message/mass/delete", json=body.model_dump()
    )


@router.post("/mass/speed/get", operation_id="message_mass_speed_get")
async def mass_speed_get() -> dict[str, Any]:
    """获取群发速度 (/cgi-bin/message/mass/speed/get)."""
    return await wechat_client.call_json("POST", "/cgi-bin/message/mass/speed/get")


@router.post("/mass/speed/set", operation_id="message_mass_speed_set")
async def mass_speed_set(body: MassSpeedBody) -> dict[str, Any]:
    """设置群发速度 (/cgi-bin/message/mass/speed/set)."""
    return await wechat_client.call_json(
        "POST", "/cgi-bin/message/mass/speed/set", json=body.model_dump()
    )


@router.post("/mass/get", operation_id="message_mass_get")
async def mass_get(body: MassGetBody) -> dict[str, Any]:
    """查询群发消息发送状态 (/cgi-bin/message/mass/get)."""
    return await wechat_client.call_json(
        "POST", "/cgi-bin/message/mass/get", json=body.model_dump()
    )


@router.post("/mass/preview", operation_id="message_mass_preview")
async def mass_preview(body: MassPreviewBody) -> dict[str, Any]:
    """预览消息 (/cgi-bin/message/mass/preview)."""
    return await wechat_client.call_json(
        "POST",
        "/cgi-bin/message/mass/preview",
        json=body.model_dump(exclude_none=True),
    )


@router.post("/mass/sendall", operation_id="message_mass_sendall")
async def mass_sendall(body: MassSendAllBody) -> dict[str, Any]:
    """根据标签群发消息 (/cgi-bin/message/mass/sendall)."""
    return await wechat_client.call_json(
        "POST", "/cgi-bin/message/mass/sendall", json=body.model_dump()
    )


@router.post("/mass/uploadnews", operation_id="message_mass_uploadnews")
async def mass_uploadnews(body: UploadNewsBody) -> dict[str, Any]:
    """上传图文消息素材 (/cgi-bin/media/uploadnews)."""
    return await wechat_client.call_json(
        "POST", "/cgi-bin/media/uploadnews", json=body.model_dump()
    )


# -------- 一次性订阅消息 --------


class SubscribeSendBody(BaseModel):
    """一次性订阅消息 (/cgi-bin/message/template/subscribe)."""

    model_config = ConfigDict(extra="allow")

    touser: str
    template_id: str
    url: str | None = None
    scene: str = Field(..., description="订阅场景值 scene，必填")
    title: str = Field(..., description="消息标题，必填")
    data: dict[str, Any] = Field(
        ..., description="{'key': {'value': str, 'color': '#RRGGBB'}, ...}"
    )


@router.post("/subscribe/send", operation_id="message_subscribe_send")
async def subscribe_send(body: SubscribeSendBody) -> dict[str, Any]:
    """发送一次性订阅消息 (/cgi-bin/message/template/subscribe)."""
    return await wechat_client.call_json(
        "POST",
        "/cgi-bin/message/template/subscribe",
        json=body.model_dump(exclude_none=True),
    )


# -------- 自动回复 --------


@router.get("/autoreply/info", operation_id="message_autoreply_info")
async def autoreply_info() -> dict[str, Any]:
    """获取公众号的自动回复规则 (/cgi-bin/get_current_autoreply_info)."""
    return await wechat_client.call_json("GET", "/cgi-bin/get_current_autoreply_info")
