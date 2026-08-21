"""公众号消息推送回调 — URL 验证 + subscribe/unsubscribe 事件.

这条回调是关注门禁的数据来源：微信没有 unionid → openid 的转换接口，只能靠
关注/取关事件实时维护名单（全量拉粉丝列表只用于冷启动兜底）。
"""

import logging
import re

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from ..config import settings
from ..customer_service.crypto import CallbackCrypto, InvalidSignature
from ..followers import follower_directory

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/wechat", tags=["wechat"])


def _crypto() -> CallbackCrypto:
    if not settings.wechat_callback_token or not settings.wechat_aes_key:
        raise HTTPException(500, "WECHAT_CALLBACK_TOKEN / WECHAT_AES_KEY not configured")
    return CallbackCrypto(
        token=settings.wechat_callback_token,
        aes_key=settings.wechat_aes_key,
        receive_id=settings.wechat_appid,
    )


def _xml_field(xml: str, tag: str) -> str:
    m = re.search(rf"<{tag}><!\[CDATA\[(.*?)\]\]></{tag}>", xml) or re.search(
        rf"<{tag}>(.*?)</{tag}>", xml
    )
    return m.group(1) if m else ""


async def _apply_follow_event(event: str, openid: str) -> None:
    """跑在 BackgroundTask 里，响应已发出——异常只能自己消化掉."""
    try:
        if event == "subscribe":
            await follower_directory.record_subscribe(openid)
        else:
            await follower_directory.record_unsubscribe(openid)
    except Exception:
        logger.exception("failed to apply %s for %s", event, openid)


@router.get("/callback", operation_id="wechat_callback_verify")
async def callback_verify(
    signature: str = Query(...),
    timestamp: str = Query(...),
    nonce: str = Query(...),
    echostr: str = Query(...),
) -> PlainTextResponse:
    """后台配置消息推送时的一次性校验：验签后原样回显 echostr（不解密）."""
    try:
        _crypto().verify_plain_signature(signature, timestamp, nonce)
    except (InvalidSignature, ValueError) as exc:
        raise HTTPException(403, f"signature verification failed: {exc}") from exc
    return PlainTextResponse(echostr)


@router.post("/callback", operation_id="wechat_callback_event")
async def callback_event(
    request: Request,
    background: BackgroundTasks,
    timestamp: str = Query(...),
    nonce: str = Query(...),
    msg_signature: str = Query(""),
) -> PlainTextResponse:
    """接收公众号事件；只关心 subscribe/unsubscribe，其余一律放过并回 success.

    回 "success" 而不是空串或消息体：我们不在这里做自动回复，让微信不再重试即可。
    """
    body = (await request.body()).decode()
    encrypted = _xml_field(body, "Encrypt")
    if encrypted:
        try:
            xml = _crypto().decrypt_message(msg_signature, timestamp, nonce, encrypted)
        except (InvalidSignature, ValueError) as exc:
            raise HTTPException(403, f"signature verification failed: {exc}") from exc
    else:
        # 明文/兼容模式
        xml = body

    if _xml_field(xml, "MsgType") == "event":
        event = _xml_field(xml, "Event").lower()
        if event in ("subscribe", "unsubscribe"):
            background.add_task(_apply_follow_event, event, _xml_field(xml, "FromUserName"))
    return PlainTextResponse("success")
