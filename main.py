from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Query
from fastapi_mcp import FastApiMCP
from pydantic import BaseModel, Field

from app.auth import api_key_middleware
from app.config import settings
from app.routers import draft as draft_router
from app.routers import freepublish as freepublish_router
from app.routers import material as material_router
from app.routers import message as message_router
from app.wechat import wechat_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await wechat_client.close()


app = FastAPI(
    title="WeChat OAP API",
    description="FastAPI wrapper for WeChat 订阅号 基础接口 with MCP support.",
    version="0.1.0",
    lifespan=lifespan,
)
app.middleware("http")(api_key_middleware)


class ClearQuotaBody(BaseModel):
    appid: str | None = Field(default=None, description="AppID; defaults to WECHAT_APPID env")


class CallbackCheckBody(BaseModel):
    action: str = Field(default="all", description="all | dns | ping")
    check_operator: str = Field(
        default="DEFAULT", description="DEFAULT | CHINANET | UNICOM | CAP | DNSPOD"
    )


@app.get("/healthz", operation_id="healthz", tags=["meta"])
async def healthz() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok"}


@app.get("/wechat/token", operation_id="get_access_token", tags=["wechat"])
async def get_access_token(
    force_refresh: bool = Query(False, description="Bypass local cache and re-fetch"),
) -> dict[str, Any]:
    """获取 Access Token (/cgi-bin/token). Uses AppID/AppSecret from env."""
    return await wechat_client.fetch_access_token(force_refresh=force_refresh)


@app.get("/wechat/stable-token", operation_id="get_stable_token", tags=["wechat"])
async def get_stable_token(
    force_refresh: bool = Query(False, description="Force WeChat to issue a new token"),
) -> dict[str, Any]:
    """获取稳定版 Access Token (/cgi-bin/stable_token)."""
    return await wechat_client.fetch_stable_token(force_refresh=force_refresh)


@app.post("/wechat/callback/check", operation_id="callback_check", tags=["wechat"])
async def callback_check(body: CallbackCheckBody) -> dict[str, Any]:
    """网络检测 (/cgi-bin/callback/check)."""
    return await wechat_client.callback_check(
        action=body.action, check_operator=body.check_operator
    )


@app.get("/wechat/api-domain-ip", operation_id="get_api_domain_ip", tags=["wechat"])
async def get_api_domain_ip() -> dict[str, Any]:
    """获取微信 API 接口 IP 段 (/cgi-bin/get_api_domain_ip)."""
    return await wechat_client.get_api_domain_ip()


@app.get("/wechat/callback-ip", operation_id="get_callback_ip", tags=["wechat"])
async def get_callback_ip() -> dict[str, Any]:
    """获取微信 callback IP (/cgi-bin/getcallbackip)."""
    return await wechat_client.get_callback_ip()


@app.post("/wechat/clear-quota", operation_id="clear_quota", tags=["wechat"])
async def clear_quota(body: ClearQuotaBody) -> dict[str, Any]:
    """重置 API 调用次数 (/cgi-bin/clear_quota)."""
    return await wechat_client.clear_quota(appid=body.appid)


app.include_router(freepublish_router.router)
app.include_router(draft_router.router)
app.include_router(material_router.router)
app.include_router(message_router.router)


# MCP exposes a DELIBERATELY NARROW subset — only what's needed to build and
# inspect drafts + upload the media they reference. Publishing (freepublish_*)
# and messaging (message_*) stay reachable via the HTTP routes (/docs) but are
# NOT exposed to agents, to keep the agent-visible tool surface aligned with
# the intended "compose drafts; I'll publish by hand" workflow.
MCP_TOOLS = [
    # sanity-check
    "healthz",
    # draft lifecycle
    "draft_add",
    "draft_update",
    "draft_get",
    "draft_batchget",
    "draft_count",
    "draft_delete",
    "draft_switch",
    "draft_product_cardinfo",
    # material (needed to supply thumb_media_id + inline images)
    "material_get",
    "material_count",
    "material_batchget",
    "material_delete",
    "material_uploadimg",
    "material_add",
    "material_temp_upload",
    "material_temp_get",
    "material_temp_get_jssdk",
]

mcp = FastApiMCP(
    app,
    name="wechat-oap-mcp",
    description="WeChat 公众号 草稿 & 素材 exposed as MCP tools.",
    include_operations=MCP_TOOLS,
    # Forward the API key header from incoming MCP requests into internal tool calls
    # so they pass our middleware (otherwise 401 on every tool invocation).
    headers=["authorization", settings.api_key_header.lower()],
)
mcp.mount_http(mount_path="/mcp")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host=settings.host, port=settings.port, reload=True)
