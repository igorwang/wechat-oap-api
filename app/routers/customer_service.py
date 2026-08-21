"""微信客服回调端点 — GET URL 验证 + POST 加密事件接收."""

import re

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from ..config import settings
from ..customer_service.bot import support_bot
from ..customer_service.crypto import CallbackCrypto, InvalidSignature

router = APIRouter(prefix="/customer-service", tags=["customer-service"])


def _crypto() -> CallbackCrypto:
    if not settings.cs_callback_token or not settings.cs_aes_key:
        raise HTTPException(500, "CS_CALLBACK_TOKEN / CS_AES_KEY not configured")
    return CallbackCrypto(
        token=settings.cs_callback_token,
        aes_key=settings.cs_aes_key,
        receive_id=settings.cs_corpid,
    )


def _xml_field(xml: str, tag: str) -> str:
    m = re.search(rf"<{tag}><!\[CDATA\[(.*?)\]\]></{tag}>", xml) or re.search(
        rf"<{tag}>(.*?)</{tag}>", xml
    )
    return m.group(1) if m else ""


@router.get("/callback", operation_id="cs_callback_verify")
async def callback_verify(
    msg_signature: str = Query(...),
    timestamp: str = Query(...),
    nonce: str = Query(...),
    echostr: str = Query(...),
) -> PlainTextResponse:
    """微信客服后台配置回调 URL 时的一次性校验：验签并回显解密后的 echostr."""
    try:
        plain = _crypto().verify_url(msg_signature, timestamp, nonce, echostr)
    except (InvalidSignature, ValueError) as exc:
        raise HTTPException(403, f"signature verification failed: {exc}") from exc
    return PlainTextResponse(plain)


@router.post("/callback", operation_id="cs_callback_event")
async def callback_event(
    request: Request,
    background: BackgroundTasks,
    msg_signature: str = Query(...),
    timestamp: str = Query(...),
    nonce: str = Query(...),
) -> PlainTextResponse:
    """接收 kf_msg_or_event 事件：验签解密后交给机器人异步处理，立即返回 200."""
    body = (await request.body()).decode()
    encrypted = _xml_field(body, "Encrypt")
    try:
        plain_xml = _crypto().decrypt_message(msg_signature, timestamp, nonce, encrypted)
    except (InvalidSignature, ValueError) as exc:
        raise HTTPException(403, f"signature verification failed: {exc}") from exc

    sync_token = _xml_field(plain_xml, "Token")
    open_kfid = _xml_field(plain_xml, "OpenKfId")
    background.add_task(support_bot.process_event, token=sync_token, open_kfid=open_kfid)
    return PlainTextResponse("success")
