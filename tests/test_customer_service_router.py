"""/customer-service/callback — 微信客服回调端点（GET 验证 + POST 事件）."""

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from main import app

# 与 test_customer_service_crypto.py 同一组预计算向量
TOKEN = "TestCallbackToken"
AES_KEY = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQ"
CORPID = "ww1234567890abcdef"
TS = "1700000000"
NONCE = "nonce123"

ECHO_PLAIN = "8964103459665061180"
ECHO_ENC = "B4PcXgtThYsrOQnzxvXRUD3gwtL07Jdvp+c3FmjtNAUkrYBM5aBTCQfxoHEdguAy8zQrV4vNxW0PsT12iAQCTw=="
ECHO_SIG = "13bc594fc5cfa86b8141f09a5560463e19b01b22"

EVENT_ENC = (
    "B4PcXgtThYsrOQnzxvXRUJpbfQleP/DOOYPU6TX8a7Rae8eLZXP0as9yIjyUaw4HvDP47ckPJ/n79uD9atGcN7"
    "MF4uSmg+7JHZglBcfRVe+Jaon48Tl48g9XQwPERiGRek69Uad440FGS6xt3wnf5rlxgUfBJRA9SirgRNQkItA+"
    "xtr5aTW5YRV+5d3OQE2rijE4anY+PIQZ95eM7kgOyblaLDP6sZaKqh5xiSe+PlidwtCubRQoyOxrGQCFHQ4hoy"
    "eQ8BbHh0EkYMLeo6X5R59h11SDk6mFw0aDk5SmuFvh8/tfgRuNHKgoxNlJLJ6veS80Lsp3Hg7JgFBm7Z4xunEo"
    "SCXBE8qT7g4R/mpMBicHIfado8TMqTltDOggFMaeG5RcEyExq0uY0mLiLCRnkyOsisnKDPpcczP9rG7raRg="
)
EVENT_SIG = "5bf7ad4143f1caa0d89d0c20d9f35906ad6debb7"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "cs_callback_token", TOKEN)
    monkeypatch.setattr(settings, "cs_aes_key", AES_KEY)
    monkeypatch.setattr(settings, "cs_corpid", CORPID)
    with TestClient(app) as c:
        yield c


def _params(sig, echostr=None):
    p = {"msg_signature": sig, "timestamp": TS, "nonce": NONCE}
    if echostr is not None:
        p["echostr"] = echostr
    return p


def test_get_verify_returns_decrypted_echostr(client):
    r = client.get("/customer-service/callback", params=_params(ECHO_SIG, ECHO_ENC))
    assert r.status_code == 200
    assert r.text == ECHO_PLAIN


def test_get_verify_rejects_bad_signature(client):
    r = client.get("/customer-service/callback", params=_params("0" * 40, ECHO_ENC))
    assert r.status_code == 403


def test_post_event_triggers_bot_and_returns_success(client, monkeypatch):
    calls = []

    async def fake_process_event(*, token="", open_kfid=""):
        calls.append({"token": token, "open_kfid": open_kfid})
        return 1

    from app.routers import customer_service as cs_router

    monkeypatch.setattr(cs_router.support_bot, "process_event", fake_process_event)

    body = f"<xml><ToUserName><![CDATA[{CORPID}]]></ToUserName><Encrypt><![CDATA[{EVENT_ENC}]]></Encrypt></xml>"
    r = client.post(
        "/customer-service/callback",
        params=_params(EVENT_SIG),
        content=body,
        headers={"Content-Type": "text/xml"},
    )
    assert r.status_code == 200
    # 解密出的事件 XML 里的 Token / OpenKfId 应传给机器人
    assert calls == [{"token": "ENCSyncToken123", "open_kfid": "wkAJ2GCAAA_test"}]


def test_post_event_rejects_bad_signature(client, monkeypatch):
    called = []

    async def fake_process_event(**kwargs):
        called.append(kwargs)
        return 0

    from app.routers import customer_service as cs_router

    monkeypatch.setattr(cs_router.support_bot, "process_event", fake_process_event)

    body = f"<xml><Encrypt><![CDATA[{EVENT_ENC}]]></Encrypt></xml>"
    r = client.post(
        "/customer-service/callback",
        params=_params("0" * 40),
        content=body,
        headers={"Content-Type": "text/xml"},
    )
    assert r.status_code == 403
    assert called == []


def test_callback_exempt_from_api_key(client, monkeypatch):
    monkeypatch.setattr(settings, "api_key", "sekret")
    r = client.get("/customer-service/callback", params=_params(ECHO_SIG, ECHO_ENC))
    assert r.status_code == 200
    assert r.text == ECHO_PLAIN
