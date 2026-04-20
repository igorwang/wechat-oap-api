"""素材管理 (material) — permanent + temporary, incl. multipart uploads."""

from typing import Any, Literal

from fastapi import APIRouter, File, Form, Query, Response, UploadFile
from pydantic import BaseModel, Field

from ..wechat import wechat_client

router = APIRouter(prefix="/wechat/material", tags=["wechat"])


MaterialType = Literal["image", "voice", "video", "thumb"]


# -------- permanent material --------


class MediaIdBody(BaseModel):
    media_id: str


class BatchGetBody(BaseModel):
    type: MaterialType
    offset: int = Field(0, ge=0)
    count: int = Field(20, ge=1, le=20)


@router.post("/permanent/get", operation_id="material_get")
async def get_material(body: MediaIdBody) -> dict[str, Any]:
    """获取永久素材 (/cgi-bin/material/get_material). 对图片/语音/缩略图 WeChat 直接返回
    二进制，本接口仍按 JSON 转发；需要 raw bytes 时直接走微信。"""
    return await wechat_client.call_json(
        "POST", "/cgi-bin/material/get_material", json=body.model_dump()
    )


@router.get("/permanent/count", operation_id="material_count")
async def count_material() -> dict[str, Any]:
    """获取永久素材总数 (/cgi-bin/material/get_materialcount)."""
    return await wechat_client.call_json("GET", "/cgi-bin/material/get_materialcount")


@router.post("/permanent/batchget", operation_id="material_batchget")
async def batchget_material(body: BatchGetBody) -> dict[str, Any]:
    """获取永久素材列表 (/cgi-bin/material/batchget_material)."""
    return await wechat_client.call_json(
        "POST", "/cgi-bin/material/batchget_material", json=body.model_dump()
    )


@router.post("/permanent/delete", operation_id="material_delete")
async def delete_material(body: MediaIdBody) -> dict[str, Any]:
    """删除永久素材 (/cgi-bin/material/del_material)."""
    return await wechat_client.call_json(
        "POST", "/cgi-bin/material/del_material", json=body.model_dump()
    )


@router.post("/permanent/uploadimg", operation_id="material_uploadimg")
async def uploadimg(media: UploadFile = File(...)) -> dict[str, Any]:
    """上传发表内容中的图片 (/cgi-bin/media/uploadimg). 返回 {url}."""
    contents = await media.read()
    return await wechat_client.call_multipart(
        "POST",
        "/cgi-bin/media/uploadimg",
        files={"media": (media.filename or "image", contents, media.content_type)},
    )


@router.post("/permanent/add", operation_id="material_add")
async def add_material(
    type: MaterialType = Query(...),
    media: UploadFile = File(...),
    title: str | None = Form(None, description="视频素材必填"),
    introduction: str | None = Form(None, description="视频素材必填"),
) -> dict[str, Any]:
    """新增永久素材 (/cgi-bin/material/add_material). 视频类型需要额外 description."""
    import json as _json

    contents = await media.read()
    files = {"media": (media.filename or "file", contents, media.content_type)}
    data: dict[str, Any] = {}
    if type == "video":
        data["description"] = _json.dumps(
            {"title": title or "", "introduction": introduction or ""},
            ensure_ascii=False,
        )
    return await wechat_client.call_multipart(
        "POST",
        "/cgi-bin/material/add_material",
        params={"type": type},
        data=data,
        files=files,
    )


# -------- temporary material --------


@router.post("/temporary/upload", operation_id="material_temp_upload")
async def temp_upload(
    type: MaterialType = Query(...),
    media: UploadFile = File(...),
) -> dict[str, Any]:
    """新增临时素材 (/cgi-bin/media/upload)."""
    contents = await media.read()
    return await wechat_client.call_multipart(
        "POST",
        "/cgi-bin/media/upload",
        params={"type": type},
        files={"media": (media.filename or "file", contents, media.content_type)},
    )


@router.get("/temporary/get", operation_id="material_temp_get")
async def temp_get(media_id: str = Query(...)) -> Response:
    """获取临时素材 (/cgi-bin/media/get). 返回二进制（视频则返回 JSON）。"""
    token = await wechat_client.get_cached_access_token()
    r = await wechat_client._client.get(
        "/cgi-bin/media/get", params={"access_token": token, "media_id": media_id}
    )
    ctype = r.headers.get("content-type", "application/octet-stream")
    return Response(content=r.content, media_type=ctype)


@router.get("/temporary/get-jssdk", operation_id="material_temp_get_jssdk")
async def temp_get_jssdk(media_id: str = Query(...)) -> Response:
    """获取高清语音素材 (/cgi-bin/media/get/jssdk). 返回二进制。"""
    token = await wechat_client.get_cached_access_token()
    r = await wechat_client._client.get(
        "/cgi-bin/media/get/jssdk",
        params={"access_token": token, "media_id": media_id},
    )
    ctype = r.headers.get("content-type", "application/octet-stream")
    return Response(content=r.content, media_type=ctype)
