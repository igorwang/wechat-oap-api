"""公众号消息推送回调 — URL 验证 + subscribe/unsubscribe 事件.

公众号的 URL 验证跟企业微信不是一套：签名只由 token/timestamp/nonce 三者算出
（不含 echostr），且 echostr 原样返回、不解密。POST 安全模式的解密算法则相同，
只是 receive_id 用 AppID。
"""

import base64
import hashlib
import os
import struct

import httpx
import pytest
import respx
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from fastapi.testclient import TestClient

from app.config import settings

TOKEN = "tok_test"
AES_KEY = base64.b64encode(os.urandom(32)).decode()[:43]
APPID = "wxappid_test"
API = "https://api.weixin.qq.com"


@pytest.fixture(autouse=True)
def configure(monkeypatch):
    monkeypatch.setattr(settings, "wechat_callback_token", TOKEN)
    monkeypatch.setattr(settings, "wechat_aes_key", AES_KEY)
    monkeypatch.setattr(settings, "wechat_appid", APPID)
    monkeypatch.setattr(settings, "wechat_appsecret", "secret1")
    monkeypatch.setattr(settings, "api_key", "")


@pytest.fixture
def client():
    from main import app

    return TestClient(app)


@pytest.fixture(autouse=True)
def fresh_directory():
    """每个用例都用干净的关注名单，避免互相污染."""
    from app.followers import follower_directory

    follower_directory._unionids = set()
    follower_directory._fetched_at = 0.0
    yield follower_directory


def _plain_signature(timestamp: str, nonce: str) -> str:
    return hashlib.sha1("".join(sorted([TOKEN, timestamp, nonce])).encode()).hexdigest()


def _encrypt(xml: str) -> str:
    key = base64.b64decode(AES_KEY + "=")
    raw = os.urandom(16) + struct.pack("!I", len(xml.encode())) + xml.encode() + APPID.encode()
    pad = 32 - len(raw) % 32
    raw += bytes([pad]) * pad
    enc = Cipher(algorithms.AES(key), modes.CBC(key[:16])).encryptor()
    return base64.b64encode(enc.update(raw) + enc.finalize()).decode()


def _msg_signature(timestamp: str, nonce: str, encrypted: str) -> str:
    return hashlib.sha1(
        "".join(sorted([TOKEN, timestamp, nonce, encrypted])).encode()
    ).hexdigest()


def _event_xml(event: str, openid: str) -> str:
    return (
        f"<xml><ToUserName><![CDATA[gh_test]]></ToUserName>"
        f"<FromUserName><![CDATA[{openid}]]></FromUserName>"
        f"<CreateTime>1787300000</CreateTime>"
        f"<MsgType><![CDATA[event]]></MsgType>"
        f"<Event><![CDATA[{event}]]></Event></xml>"
    )


def _post_event(client, xml: str):
    encrypted = _encrypt(xml)
    ts, nonce = "1787300000", "n1"
    return client.post(
        "/wechat/callback",
        params={
            "signature": _plain_signature(ts, nonce),
            "timestamp": ts,
            "nonce": nonce,
            "msg_signature": _msg_signature(ts, nonce, encrypted),
            "encrypt_type": "aes",
        },
        content=f"<xml><Encrypt><![CDATA[{encrypted}]]></Encrypt></xml>",
        headers={"Content-Type": "text/xml"},
    )


def test_url_verification_echoes_echostr_verbatim(client):
    """公众号回显的是原始 echostr，不解密——跟企业微信不同."""
    ts, nonce = "1787300000", "n1"
    resp = client.get(
        "/wechat/callback",
        params={"signature": _plain_signature(ts, nonce), "timestamp": ts,
                "nonce": nonce, "echostr": "hello_plain"},
    )
    assert resp.status_code == 200
    assert resp.text == "hello_plain"


def test_url_verification_rejects_bad_signature(client):
    resp = client.get(
        "/wechat/callback",
        params={"signature": "deadbeef", "timestamp": "1787300000",
                "nonce": "n1", "echostr": "hello_plain"},
    )
    assert resp.status_code == 403


def test_subscribe_event_marks_follower(client, fresh_directory):
    with respx.mock(base_url=API) as mock:
        mock.get("/cgi-bin/token").mock(
            return_value=httpx.Response(200, json={"access_token": "T", "expires_in": 7200})
        )
        mock.get("/cgi-bin/user/info").mock(
            return_value=httpx.Response(200, json={"subscribe": 1, "openid": "o_new",
                                                   "unionid": "u_new"})
        )

        resp = _post_event(client, _event_xml("subscribe", "o_new"))

        assert resp.status_code == 200
        assert resp.text == "success"
        assert "u_new" in fresh_directory._unionids


def test_unsubscribe_event_drops_follower(client, fresh_directory):
    fresh_directory._unionids = {"u_gone"}
    with respx.mock(base_url=API) as mock:
        mock.get("/cgi-bin/token").mock(
            return_value=httpx.Response(200, json={"access_token": "T", "expires_in": 7200})
        )
        mock.get("/cgi-bin/user/info").mock(
            return_value=httpx.Response(200, json={"subscribe": 0, "openid": "o_gone",
                                                   "unionid": "u_gone"})
        )

        resp = _post_event(client, _event_xml("unsubscribe", "o_gone"))

        assert resp.status_code == 200
        assert "u_gone" not in fresh_directory._unionids


def test_unrelated_message_is_accepted_without_touching_followers(client, fresh_directory):
    """普通文本消息不该改动关注名单，也不该报错."""
    xml = (
        "<xml><ToUserName><![CDATA[gh_test]]></ToUserName>"
        "<FromUserName><![CDATA[o_x]]></FromUserName>"
        "<CreateTime>1787300000</CreateTime>"
        "<MsgType><![CDATA[text]]></MsgType>"
        "<Content><![CDATA[你好]]></Content></xml>"
    )
    resp = _post_event(client, xml)
    assert resp.status_code == 200
    assert resp.text == "success"
    assert fresh_directory._unionids == set()


def test_event_post_rejects_bad_msg_signature(client):
    encrypted = _encrypt(_event_xml("subscribe", "o_new"))
    resp = client.post(
        "/wechat/callback",
        params={"signature": "x", "timestamp": "1787300000", "nonce": "n1",
                "msg_signature": "deadbeef", "encrypt_type": "aes"},
        content=f"<xml><Encrypt><![CDATA[{encrypted}]]></Encrypt></xml>",
        headers={"Content-Type": "text/xml"},
    )
    assert resp.status_code == 403


# ---- 落库路径：关注状态存 DB，取关不依赖 user/info ----


@pytest.fixture
async def db_directory():
    """把 follower_directory 接到一个真实（SQLite）库上，用完还原."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.customer_service.models import Base
    from app.follower_store import FollowerStore
    from app.followers import follower_directory

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    follower_directory.store = FollowerStore(async_sessionmaker(engine, expire_on_commit=False))
    yield follower_directory
    follower_directory.store = None
    await engine.dispose()


async def test_subscribe_then_unsubscribe_flips_gate_via_db(client, db_directory):
    """完整走一遍：关注 → 门禁放行；取关 → 门禁拦下。全部以库为准."""
    with respx.mock(base_url=API) as mock:
        mock.get("/cgi-bin/token").mock(
            return_value=httpx.Response(200, json={"access_token": "T", "expires_in": 7200})
        )
        user_info = mock.get("/cgi-bin/user/info").mock(
            return_value=httpx.Response(200, json={"subscribe": 1, "openid": "o_a",
                                                   "unionid": "u_a"})
        )

        assert _post_event(client, _event_xml("subscribe", "o_a")).status_code == 200
        assert await db_directory.store.is_follower("u_a") is True
        assert user_info.call_count == 1

        assert _post_event(client, _event_xml("unsubscribe", "o_a")).status_code == 200

        assert await db_directory.store.is_follower("u_a") is False
        # 取关后 user/info 不再返回 unionid，所以这条路必须不依赖它
        assert user_info.call_count == 1, "取关不应再调 user/info"


async def test_resubscribe_restores_access(client, db_directory):
    with respx.mock(base_url=API) as mock:
        mock.get("/cgi-bin/token").mock(
            return_value=httpx.Response(200, json={"access_token": "T", "expires_in": 7200})
        )
        mock.get("/cgi-bin/user/info").mock(
            return_value=httpx.Response(200, json={"subscribe": 1, "openid": "o_b",
                                                   "unionid": "u_b"})
        )
        _post_event(client, _event_xml("subscribe", "o_b"))
        _post_event(client, _event_xml("unsubscribe", "o_b"))
        assert await db_directory.store.is_follower("u_b") is False

        _post_event(client, _event_xml("subscribe", "o_b"))

        assert await db_directory.store.is_follower("u_b") is True
