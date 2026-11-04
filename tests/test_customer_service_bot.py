"""SupportBot — 回调事件驱动的机器人编排：拉取消息 → DeepSeek 生成 → 客服回复."""

import json

import httpx
import pytest
import respx

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.customer_service.bot import SupportBot
from app.customer_service.client import CustomerServiceClient
from app.customer_service.models import Base
from app.customer_service.store import CustomerStore

QY = "https://qyapi.weixin.qq.com"
DS = "https://api.deepseek.com"


@pytest.fixture
async def store():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield CustomerStore(async_sessionmaker(engine, expire_on_commit=False))
    await engine.dispose()


@pytest.fixture
def client(tmp_path):
    return CustomerServiceClient(
        corpid="test_corpid",
        secret="test_cs_secret",
        base_url=QY,
        cursor_path=str(tmp_path / "cursor.json"),
    )


@pytest.fixture
def perception():
    from app.customer_service.perception import Perception

    return Perception(
        api_key="dash-test-key",
        api_base="https://dashscope.aliyuncs.com/compatible-mode/v1",
        asr_model="qwen3-asr-flash",
        vl_model="qwen3-vl-flash",
    )


@pytest.fixture
def bot(client, perception):
    return SupportBot(
        client,
        api_key="ds-test-key",
        api_base=DS,
        model="deepseek-chat",
        system_prompt="你是客服",
        welcome_text="欢迎咨询",
        perception=perception,
        # 关注门禁单独测（见文件末尾），这里只关心消息收发本身
        require_follow=False,
    )


def _mock_qy_token(mock):
    mock.get(f"{QY}/cgi-bin/gettoken").mock(
        return_value=httpx.Response(200, json={"errcode": 0, "access_token": "T", "expires_in": 7200})
    )


def _mock_sync(mock, msg_list):
    return mock.post(f"{QY}/cgi-bin/kf/sync_msg").mock(
        return_value=httpx.Response(
            200, json={"errcode": 0, "next_cursor": "C1", "has_more": 0, "msg_list": msg_list}
        )
    )


async def test_text_message_gets_llm_reply(bot):
    async with respx.mock as mock:
        _mock_qy_token(mock)
        _mock_sync(mock, [{
            "msgid": "m1", "open_kfid": "wk1", "external_userid": "u1",
            "origin": 3, "msgtype": "text", "text": {"content": "怎么退货？"},
        }])
        ds_route = mock.post(f"{DS}/chat/completions").mock(
            return_value=httpx.Response(200, json={
                "choices": [{"message": {"role": "assistant", "content": "七天无理由退货"}}]
            })
        )
        send_route = mock.post(f"{QY}/cgi-bin/kf/send_msg").mock(
            return_value=httpx.Response(200, json={"errcode": 0, "msgid": "r1"})
        )

        handled = await bot.process_event(token="EVT", open_kfid="wk1")

        assert handled == 1
        ds_req = json.loads(ds_route.calls.last.request.content)
        assert ds_req["model"] == "deepseek-chat"
        assert ds_req["messages"][0] == {"role": "system", "content": "你是客服"}
        assert ds_req["messages"][-1] == {"role": "user", "content": "怎么退货？"}
        assert ds_route.calls.last.request.headers["authorization"] == "Bearer ds-test-key"
        sent = json.loads(send_route.calls.last.request.content)
        assert sent["touser"] == "u1"
        assert sent["open_kfid"] == "wk1"
        assert sent["text"]["content"] == "七天无理由退货"


async def test_enter_session_sends_welcome(bot):
    async with respx.mock as mock:
        _mock_qy_token(mock)
        _mock_sync(mock, [{
            "msgid": "e1", "open_kfid": "wk1", "external_userid": "u1",
            "origin": 4, "msgtype": "event",
            "event": {"event_type": "enter_session", "open_kfid": "wk1",
                      "external_userid": "u1", "welcome_code": "WC1"},
        }])
        welcome_route = mock.post(f"{QY}/cgi-bin/kf/send_msg_on_event").mock(
            return_value=httpx.Response(200, json={"errcode": 0, "msgid": "w1"})
        )

        handled = await bot.process_event(token="EVT", open_kfid="wk1")

        assert handled == 1
        body = json.loads(welcome_route.calls.last.request.content)
        assert body["code"] == "WC1"
        assert body["text"]["content"] == "欢迎咨询"


async def test_enter_session_records_customer_profile(client, store):
    """进入会话时抓取并落库客户资料——external_userid 只在 48h 内可查，必须当场存."""
    bot = SupportBot(client, api_key="k", api_base=DS, store=store, welcome_text="欢迎")
    async with respx.mock as mock:
        _mock_qy_token(mock)
        _mock_sync(mock, [{
            "msgid": "e1", "open_kfid": "wk1", "external_userid": "u1",
            "origin": 4, "msgtype": "event",
            "event": {"event_type": "enter_session", "open_kfid": "wk1",
                      "external_userid": "u1", "welcome_code": "WC1",
                      "scene": "from_ad", "scene_param": "p1"},
        }])
        mock.post(f"{QY}/cgi-bin/kf/send_msg_on_event").mock(
            return_value=httpx.Response(200, json={"errcode": 0, "msgid": "w1"})
        )
        mock.post(f"{QY}/cgi-bin/kf/customer/batchget").mock(
            return_value=httpx.Response(200, json={"errcode": 0, "customer_list": [
                {"external_userid": "u1", "nickname": "小明",
                 "avatar": "http://x/a.png", "gender": 1, "unionid": "o_union_1"}
            ]})
        )

        await bot.process_event(token="EVT", open_kfid="wk1")

        saved = await store.get("u1")
        assert saved is not None
        assert saved.nickname == "小明"
        assert saved.unionid == "o_union_1"
        assert saved.scene == "from_ad"
        assert saved.scene_param == "p1"
        assert saved.open_kfid == "wk1"


async def test_text_message_records_sender_and_counts(client, store):
    bot = SupportBot(client, api_key="k", api_base=DS, store=store)
    async with respx.mock as mock:
        _mock_qy_token(mock)
        _mock_sync(mock, [{
            "msgid": "m1", "open_kfid": "wk1", "external_userid": "u1",
            "origin": 3, "msgtype": "text", "text": {"content": "在吗"},
        }])
        mock.post(f"{DS}/chat/completions").mock(
            return_value=httpx.Response(200, json={
                "choices": [{"message": {"content": "在的"}}]})
        )
        mock.post(f"{QY}/cgi-bin/kf/send_msg").mock(
            return_value=httpx.Response(200, json={"errcode": 0, "msgid": "r1"})
        )

        await bot.process_event(token="EVT", open_kfid="wk1")

        saved = await store.get("u1")
        assert saved is not None
        assert saved.message_count == 1


async def test_bot_works_without_store(bot):
    """未配置数据库时不应影响收发消息."""
    async with respx.mock as mock:
        _mock_qy_token(mock)
        _mock_sync(mock, [{
            "msgid": "m1", "open_kfid": "wk1", "external_userid": "u1",
            "origin": 3, "msgtype": "text", "text": {"content": "hi"},
        }])
        mock.post(f"{DS}/chat/completions").mock(
            return_value=httpx.Response(200, json={
                "choices": [{"message": {"content": "hello"}}]})
        )
        mock.post(f"{QY}/cgi-bin/kf/send_msg").mock(
            return_value=httpx.Response(200, json={"errcode": 0, "msgid": "r1"})
        )
        assert await bot.process_event(token="EVT", open_kfid="wk1") == 1


async def test_process_event_never_raises_when_sync_fails(bot):
    """process_event 跑在 BackgroundTask 里；抛异常会让 starlette 在响应已发出后炸掉."""
    async with respx.mock as mock:
        _mock_qy_token(mock)
        mock.post(f"{QY}/cgi-bin/kf/sync_msg").mock(
            return_value=httpx.Response(
                200, json={"errcode": 95000, "errmsg": "invalid open_kfid", "msg_list": []}
            )
        )
        assert await bot.process_event(token="EVT", open_kfid="bad_kfid") == 0


async def test_non_customer_and_unsupported_messages_skipped(bot):
    async with respx.mock as mock:
        _mock_qy_token(mock)
        _mock_sync(mock, [
            # origin=4 系统消息（无 welcome_code 的事件）不回复
            {"msgid": "s1", "origin": 4, "msgtype": "event",
             "event": {"event_type": "msg_send_fail"}},
            # 视频/文件/位置等仍不接待
            {"msgid": "v1", "open_kfid": "wk1", "external_userid": "u1",
             "origin": 3, "msgtype": "video", "video": {"media_id": "MID"}},
            # origin=1 是客服自己发的，不能自问自答
            {"msgid": "o1", "open_kfid": "wk1", "external_userid": "u1",
             "origin": 1, "msgtype": "text", "text": {"content": "在的"}},
        ])
        handled = await bot.process_event(token="EVT", open_kfid="wk1")
        assert handled == 0


# ---- 语音与图片 ----
# 都走「先转成文字，再交给同一个大脑作答」：人设和不许编造的约束只有 SYSTEM_PROMPT
# 一处。微信客服的语音是 AMR（sync_msg voice_format=0），qwen3-asr-flash 直接能读，
# 不需要转码——这条是拿真的 AMR 语音打接口验过的。

DASH = "https://dashscope.aliyuncs.com/compatible-mode/v1"

AMR_BYTES = b"#!AMR\n" + (b"\x04" + b"\x00" * 12) * 50
JPEG_BYTES = b"\xff\xd8\xff\xe0fake"


def _mock_media_get(mock, content, content_type):
    return mock.get(f"{QY}/cgi-bin/media/get").mock(
        return_value=httpx.Response(200, content=content, headers={"content-type": content_type})
    )


def _mock_dashscope(mock, content):
    return mock.post(f"{DASH}/chat/completions").mock(
        return_value=httpx.Response(
            200, json={"choices": [{"message": {"role": "assistant", "content": content}}]}
        )
    )


def _mock_deepseek(mock, content):
    return mock.post(f"{DS}/chat/completions").mock(
        return_value=httpx.Response(
            200, json={"choices": [{"message": {"role": "assistant", "content": content}}]}
        )
    )


def _voice_msg(media_id="VOICE_MID"):
    return {"msgid": "vm1", "open_kfid": "wk1", "external_userid": "u1",
            "origin": 3, "msgtype": "voice", "voice": {"media_id": media_id}}


def _image_msg(media_id="IMG_MID"):
    return {"msgid": "im1", "open_kfid": "wk1", "external_userid": "u1",
            "origin": 3, "msgtype": "image", "image": {"media_id": media_id}}


async def test_voice_message_is_transcribed_then_answered(bot):
    async with respx.mock as mock:
        _mock_qy_token(mock)
        _mock_sync(mock, [_voice_msg()])
        media = _mock_media_get(mock, AMR_BYTES, "audio/amr")
        asr = _mock_dashscope(mock, "你们的退货政策是怎么样的")
        ds = _mock_deepseek(mock, "七天无理由退货")
        send = mock.post(f"{QY}/cgi-bin/kf/send_msg").mock(
            return_value=httpx.Response(200, json={"errcode": 0, "msgid": "r1"})
        )

        assert await bot.process_event(token="EVT", open_kfid="wk1") == 1

        assert media.calls.last.request.url.params["media_id"] == "VOICE_MID"
        assert asr.called
        # 转写结果原样作为客户的话交给大脑，不加任何转述
        ds_req = json.loads(ds.calls.last.request.content)
        assert ds_req["messages"][-1] == {"role": "user", "content": "你们的退货政策是怎么样的"}
        assert json.loads(send.calls.last.request.content)["text"]["content"] == "七天无理由退货"


async def test_image_message_is_described_then_answered(bot):
    async with respx.mock as mock:
        _mock_qy_token(mock)
        _mock_sync(mock, [_image_msg()])
        media = _mock_media_get(mock, JPEG_BYTES, "image/jpeg")
        vl = _mock_dashscope(mock, "一张订单截图，订单号 20260821，状态『已发货』")
        ds = _mock_deepseek(mock, "您的订单已经发出了")
        send = mock.post(f"{QY}/cgi-bin/kf/send_msg").mock(
            return_value=httpx.Response(200, json={"errcode": 0, "msgid": "r1"})
        )

        assert await bot.process_event(token="EVT", open_kfid="wk1") == 1

        assert media.calls.last.request.url.params["media_id"] == "IMG_MID"
        assert json.loads(vl.calls.last.request.content)["model"] == "qwen3-vl-flash"
        # DeepSeek 看不见图，必须明确告诉它这段文字是图片内容而不是客户原话
        asked = json.loads(ds.calls.last.request.content)["messages"][-1]["content"]
        assert "订单号 20260821" in asked
        assert "图片" in asked
        assert json.loads(send.calls.last.request.content)["text"]["content"] == "您的订单已经发出了"


async def test_octet_stream_image_is_typed_from_its_bytes(bot):
    """微信有时把图片回成 application/octet-stream，百炼只认 png/jpeg/webp."""
    async with respx.mock as mock:
        _mock_qy_token(mock)
        _mock_sync(mock, [_image_msg()])
        _mock_media_get(mock, b"\x89PNG\r\n\x1a\n" + b"body", "application/octet-stream")
        vl = _mock_dashscope(mock, "一张图")
        _mock_deepseek(mock, "好的")
        mock.post(f"{QY}/cgi-bin/kf/send_msg").mock(
            return_value=httpx.Response(200, json={"errcode": 0, "msgid": "r1"})
        )

        await bot.process_event(token="EVT", open_kfid="wk1")

        parts = json.loads(vl.calls.last.request.content)["messages"][0]["content"]
        image = next(p for p in parts if p["type"] == "image_url")
        assert image["image_url"]["url"].startswith("data:image/png;base64,")


async def test_unrecognisable_media_gets_a_reply_not_silence(bot):
    """识别失败也得出声，否则客户对着空气等."""
    async with respx.mock as mock:
        _mock_qy_token(mock)
        _mock_sync(mock, [_voice_msg()])
        _mock_media_get(mock, AMR_BYTES, "audio/amr")
        mock.post(f"{DASH}/chat/completions").mock(
            return_value=httpx.Response(500, json={"message": "internal error"})
        )
        ds = mock.post(f"{DS}/chat/completions")
        send = mock.post(f"{QY}/cgi-bin/kf/send_msg").mock(
            return_value=httpx.Response(200, json={"errcode": 0, "msgid": "r1"})
        )

        assert await bot.process_event(token="EVT", open_kfid="wk1") == 1

        assert not ds.called, "没识别出内容就不该拿空话去问大脑"
        assert "文字" in json.loads(send.calls.last.request.content)["text"]["content"]


async def test_oversized_image_is_not_sent_to_the_model(bot):
    """百炼单个媒体上限 10MB，超了直接请客户改用文字，别白挨一个 400."""
    async with respx.mock as mock:
        _mock_qy_token(mock)
        _mock_sync(mock, [_image_msg()])
        _mock_media_get(mock, b"\xff\xd8\xff" + b"x" * (10 * 1024 * 1024), "image/jpeg")
        vl = mock.post(f"{DASH}/chat/completions")
        send = mock.post(f"{QY}/cgi-bin/kf/send_msg").mock(
            return_value=httpx.Response(200, json={"errcode": 0, "msgid": "r1"})
        )

        assert await bot.process_event(token="EVT", open_kfid="wk1") == 1

        assert not vl.called
        assert "文字" in json.loads(send.calls.last.request.content)["text"]["content"]


# ---- 关注公众号门禁 ----
# 判据用的是公众号关注者名单，不是客服侧的 unionid：企业微信绑定开放平台后，
# 客户发起会话就会被分配 unionid，没关注过的号也有，取关也不回收（真机实测
# 5 个客户全部有 unionid，含 1 个从未关注、1 个已取关）。

OA = "https://api.weixin.qq.com"


@pytest.fixture
def followers(monkeypatch):
    from app.config import settings
    from app.followers import FollowerDirectory
    from app.wechat import WeChatClient

    monkeypatch.setattr(settings, "wechat_appid", "appid1")
    monkeypatch.setattr(settings, "wechat_appsecret", "secret1")
    return FollowerDirectory(WeChatClient(cache_path=""), ttl=300)


def _mock_oa(mock, *, follower_unionids):
    mock.post(f"{OA}/cgi-bin/stable_token").mock(
        return_value=httpx.Response(200, json={"access_token": "OATOK", "expires_in": 7200})
    )
    openids = [f"o{i}" for i in range(len(follower_unionids))]
    mock.get(f"{OA}/cgi-bin/user/get").mock(side_effect=[
        httpx.Response(200, json={"count": len(openids), "data": {"openid": openids},
                                  "next_openid": openids[-1] if openids else ""}),
        httpx.Response(200, json={"count": 0, "data": {}, "next_openid": ""}),
    ] * 4)
    return mock.post(f"{OA}/cgi-bin/user/info/batchget").mock(side_effect=[
        httpx.Response(200, json={"user_info_list": [
            {"subscribe": 1, "openid": o, "unionid": u}
            for o, u in zip(openids, follower_unionids)
        ]})
    ] * 4)


def _gated_bot(client, followers, store=None, perception=None):
    return SupportBot(
        client, api_key="k", api_base=DS, system_prompt="你是客服",
        store=store, require_follow=True, followers=followers, perception=perception,
    )


def _mock_kf_customer(mock, unionid):
    profile = {"external_userid": "u1", "nickname": "小明"}
    if unionid:
        profile["unionid"] = unionid
    return mock.post(f"{QY}/cgi-bin/kf/customer/batchget").mock(
        return_value=httpx.Response(200, json={"errcode": 0, "customer_list": [profile]})
    )


def _customer_msg(content="怎么退货？", msgid="m1"):
    return {"msgid": msgid, "open_kfid": "wk1", "external_userid": "u1",
            "origin": 3, "msgtype": "text", "text": {"content": content}}


async def test_non_follower_gets_qrcode_instead_of_llm(client, followers):
    async with respx.mock as mock:
        _mock_qy_token(mock)
        _mock_sync(mock, [_customer_msg()])
        _mock_kf_customer(mock, "u_stranger")      # 有 unionid，但不在关注名单里
        _mock_oa(mock, follower_unionids=["u_someone_else"])
        upload = mock.post(f"{QY}/cgi-bin/media/upload").mock(
            return_value=httpx.Response(200, json={"errcode": 0, "media_id": "QR_MID"})
        )
        ds = mock.post(f"{DS}/chat/completions")
        send = mock.post(f"{QY}/cgi-bin/kf/send_msg").mock(
            return_value=httpx.Response(200, json={"errcode": 0, "msgid": "r1"})
        )

        handled = await _gated_bot(client, followers).process_event(token="EVT", open_kfid="wk1")

        assert handled == 1
        assert not ds.called, "未关注的客户不应消耗 LLM 调用"
        assert upload.call_count == 1
        bodies = [json.loads(c.request.content) for c in send.calls]
        assert [b["msgtype"] for b in bodies] == ["text", "image"]
        assert bodies[1]["image"]["media_id"] == "QR_MID"


async def test_follower_reaches_llm(client, followers):
    async with respx.mock as mock:
        _mock_qy_token(mock)
        _mock_sync(mock, [_customer_msg()])
        _mock_kf_customer(mock, "u_fan")
        _mock_oa(mock, follower_unionids=["u_fan"])
        ds = mock.post(f"{DS}/chat/completions").mock(
            return_value=httpx.Response(200, json={
                "choices": [{"message": {"content": "这个我需要帮您确认"}}]})
        )
        send = mock.post(f"{QY}/cgi-bin/kf/send_msg").mock(
            return_value=httpx.Response(200, json={"errcode": 0, "msgid": "r1"})
        )

        handled = await _gated_bot(client, followers).process_event(token="EVT", open_kfid="wk1")

        assert handled == 1
        assert ds.called
        assert json.loads(send.calls.last.request.content)["text"]["content"] == "这个我需要帮您确认"


async def test_customer_without_any_unionid_is_blocked(client, followers):
    """客服侧连 unionid 都没给，无从判断关注状态，按未关注处理."""
    async with respx.mock as mock:
        _mock_qy_token(mock)
        _mock_sync(mock, [_customer_msg()])
        _mock_kf_customer(mock, None)
        _mock_oa(mock, follower_unionids=["u_fan"])
        mock.post(f"{QY}/cgi-bin/media/upload").mock(
            return_value=httpx.Response(200, json={"errcode": 0, "media_id": "QR_MID"})
        )
        ds = mock.post(f"{DS}/chat/completions")
        mock.post(f"{QY}/cgi-bin/kf/send_msg").mock(
            return_value=httpx.Response(200, json={"errcode": 0, "msgid": "r1"})
        )

        assert await _gated_bot(client, followers).process_event(token="EVT", open_kfid="wk1") == 1
        assert not ds.called


async def test_known_unionid_is_read_from_store_not_refetched(client, followers, store):
    """库里已有 unionid 就不必每条消息都打一次客服侧 batchget."""
    await store.upsert({"external_userid": "u1", "unionid": "u_fan"})
    async with respx.mock as mock:
        _mock_qy_token(mock)
        _mock_sync(mock, [_customer_msg()])
        kf_batchget = mock.post(f"{QY}/cgi-bin/kf/customer/batchget")
        _mock_oa(mock, follower_unionids=["u_fan"])
        mock.post(f"{DS}/chat/completions").mock(
            return_value=httpx.Response(200, json={"choices": [{"message": {"content": "好的"}}]})
        )
        mock.post(f"{QY}/cgi-bin/kf/send_msg").mock(
            return_value=httpx.Response(200, json={"errcode": 0, "msgid": "r1"})
        )

        handled = await _gated_bot(client, followers, store).process_event(
            token="EVT", open_kfid="wk1")

        assert handled == 1
        assert not kf_batchget.called


async def test_qrcode_media_id_is_reused_across_messages(client, followers):
    """临时素材 3 天有效，不该每条消息都重传一次二维码."""
    async with respx.mock as mock:
        _mock_qy_token(mock)
        _mock_sync(mock, [_customer_msg("在吗", "m1"), _customer_msg("有人吗", "m2")])
        _mock_kf_customer(mock, "u_stranger")
        _mock_oa(mock, follower_unionids=[])
        upload = mock.post(f"{QY}/cgi-bin/media/upload").mock(
            return_value=httpx.Response(200, json={"errcode": 0, "media_id": "QR_MID"})
        )
        mock.post(f"{QY}/cgi-bin/kf/send_msg").mock(
            return_value=httpx.Response(200, json={"errcode": 0, "msgid": "r1"})
        )

        assert await _gated_bot(client, followers).process_event(token="EVT", open_kfid="wk1") == 2
        assert upload.call_count == 1


async def test_gate_blocks_before_any_recognition_is_paid_for(client, followers, perception):
    """未关注的客户发语音，不该先花一次 ASR 再拦——门禁必须跑在识别之前."""
    async with respx.mock as mock:
        _mock_qy_token(mock)
        _mock_sync(mock, [_voice_msg()])
        _mock_kf_customer(mock, "u_stranger")
        _mock_oa(mock, follower_unionids=[])
        media = mock.get(f"{QY}/cgi-bin/media/get")
        dash = mock.post(f"{DASH}/chat/completions")
        mock.post(f"{QY}/cgi-bin/media/upload").mock(
            return_value=httpx.Response(200, json={"errcode": 0, "media_id": "QR_MID"})
        )
        send = mock.post(f"{QY}/cgi-bin/kf/send_msg").mock(
            return_value=httpx.Response(200, json={"errcode": 0, "msgid": "r1"})
        )

        handled = await _gated_bot(client, followers, perception=perception).process_event(
            token="EVT", open_kfid="wk1"
        )

        assert handled == 1
        assert not media.called, "拦下的客户不该下载媒体"
        assert not dash.called, "拦下的客户不该消耗识别调用"
        assert [json.loads(c.request.content)["msgtype"] for c in send.calls] == ["text", "image"]


async def test_follower_sending_a_voice_message_reaches_the_llm(client, followers, perception):
    async with respx.mock as mock:
        _mock_qy_token(mock)
        _mock_sync(mock, [_voice_msg()])
        _mock_kf_customer(mock, "u_fan")
        _mock_oa(mock, follower_unionids=["u_fan"])
        _mock_media_get(mock, AMR_BYTES, "audio/amr")
        _mock_dashscope(mock, "我想查一下物流")
        ds = _mock_deepseek(mock, "麻烦提供一下订单号")
        send = mock.post(f"{QY}/cgi-bin/kf/send_msg").mock(
            return_value=httpx.Response(200, json={"errcode": 0, "msgid": "r1"})
        )

        handled = await _gated_bot(client, followers, perception=perception).process_event(
            token="EVT", open_kfid="wk1"
        )

        assert handled == 1
        assert json.loads(ds.calls.last.request.content)["messages"][-1]["content"] == "我想查一下物流"
        assert json.loads(send.calls.last.request.content)["text"]["content"] == "麻烦提供一下订单号"


# ---- 重复投递 ----
# 微信回调 5 秒内没响应就会重推，而每次回调都从存下的 cursor 重新 sync_msg。
# 两个回调并发进来会各自读到同一个 cursor、拉到同一批消息，同一条消息回两遍。


async def test_the_same_message_is_never_answered_twice(bot):
    """回调重推时 sync_msg 会把同一条消息再吐一次，不能重复作答."""
    async with respx.mock as mock:
        _mock_qy_token(mock)
        _mock_sync(mock, [_customer_msg("怎么退货？", "m1")])
        ds = _mock_deepseek(mock, "七天无理由退货")
        send = mock.post(f"{QY}/cgi-bin/kf/send_msg").mock(
            return_value=httpx.Response(200, json={"errcode": 0, "msgid": "r1"})
        )

        first = await bot.process_event(token="EVT", open_kfid="wk1")
        second = await bot.process_event(token="EVT2", open_kfid="wk1")

        assert (first, second) == (1, 0)
        assert ds.call_count == 1
        assert send.call_count == 1


async def test_concurrent_callbacks_answer_each_message_once(bot):
    """两个回调同时进来，各自 sync 到同一批消息——客户只该收到一份回复."""
    import asyncio

    async with respx.mock as mock:
        _mock_qy_token(mock)
        _mock_sync(mock, [_customer_msg("在吗", "m1"), _customer_msg("有人吗", "m2")])
        _mock_deepseek(mock, "在的")
        send = mock.post(f"{QY}/cgi-bin/kf/send_msg").mock(
            return_value=httpx.Response(200, json={"errcode": 0, "msgid": "r1"})
        )

        handled = await asyncio.gather(
            bot.process_event(token="EVT", open_kfid="wk1"),
            bot.process_event(token="EVT", open_kfid="wk1"),
        )

        assert sum(handled) == 2, "两条消息各处理一次"
        assert send.call_count == 2


async def test_duplicate_enter_session_does_not_greet_twice(bot):
    """欢迎语重复发比重复作答更刺眼."""
    event = {"msgid": "e1", "open_kfid": "wk1", "external_userid": "u1",
             "origin": 4, "msgtype": "event",
             "event": {"event_type": "enter_session", "open_kfid": "wk1",
                       "external_userid": "u1", "welcome_code": "WC1"}}
    async with respx.mock as mock:
        _mock_qy_token(mock)
        _mock_sync(mock, [event])
        welcome = mock.post(f"{QY}/cgi-bin/kf/send_msg_on_event").mock(
            return_value=httpx.Response(200, json={"errcode": 0, "msgid": "w1"})
        )

        await bot.process_event(token="EVT", open_kfid="wk1")
        await bot.process_event(token="EVT", open_kfid="wk1")

        assert welcome.call_count == 1


async def test_messages_without_msgid_are_still_answered(bot):
    """去重不能反过来吞消息：没有 msgid 就没法判重，宁可回也不能漏."""
    async with respx.mock as mock:
        _mock_qy_token(mock)
        no_id = _customer_msg("在吗", "m1")
        del no_id["msgid"]
        _mock_sync(mock, [no_id])
        _mock_deepseek(mock, "在的")
        send = mock.post(f"{QY}/cgi-bin/kf/send_msg").mock(
            return_value=httpx.Response(200, json={"errcode": 0, "msgid": "r1"})
        )

        assert await bot.process_event(token="EVT", open_kfid="wk1") == 1
        assert await bot.process_event(token="EVT", open_kfid="wk1") == 1
        assert send.call_count == 2


# ---- 不接待的消息类型 ----
# 客户发来视频/文件/位置时，静默跳过等于机器人装死；回一句说明能接住的类型，
# 客户就知道换个方式发。系统消息和客服自己发的消息仍然不回。


async def test_video_from_a_customer_gets_told_what_is_supported(bot):
    async with respx.mock as mock:
        _mock_qy_token(mock)
        _mock_sync(mock, [{
            "msgid": "vd1", "open_kfid": "wk1", "external_userid": "u1",
            "origin": 3, "msgtype": "video", "video": {"media_id": "MID"},
        }])
        ds = mock.post(f"{DS}/chat/completions")
        media = mock.get(f"{QY}/cgi-bin/media/get")
        send = mock.post(f"{QY}/cgi-bin/kf/send_msg").mock(
            return_value=httpx.Response(200, json={"errcode": 0, "msgid": "r1"})
        )

        assert await bot.process_event(token="EVT", open_kfid="wk1") == 1

        assert not ds.called, "不接待的类型不该问大脑"
        assert not media.called, "不接待的类型不该下载媒体"
        replied = json.loads(send.calls.last.request.content)["text"]["content"]
        assert "文字" in replied and "图片" in replied and "语音" in replied


async def test_system_and_servicer_messages_stay_silent(bot):
    """origin 不是 3 的消息不是客户发的，回它等于自问自答."""
    async with respx.mock as mock:
        _mock_qy_token(mock)
        _mock_sync(mock, [
            {"msgid": "s1", "origin": 4, "msgtype": "event",
             "event": {"event_type": "msg_send_fail"}},
            {"msgid": "o1", "open_kfid": "wk1", "external_userid": "u1",
             "origin": 1, "msgtype": "text", "text": {"content": "在的"}},
            {"msgid": "o2", "open_kfid": "wk1", "external_userid": "u1",
             "origin": 4, "msgtype": "video", "video": {"media_id": "MID"}},
        ])
        send = mock.post(f"{QY}/cgi-bin/kf/send_msg")

        assert await bot.process_event(token="EVT", open_kfid="wk1") == 0
        assert not send.called


async def test_unsupported_type_from_a_non_follower_still_hits_the_gate(client, followers, perception):
    """先过门禁再谈类型，不然未关注的人也能摸到服务的边界."""
    async with respx.mock as mock:
        _mock_qy_token(mock)
        _mock_sync(mock, [{
            "msgid": "vd1", "open_kfid": "wk1", "external_userid": "u1",
            "origin": 3, "msgtype": "video", "video": {"media_id": "MID"},
        }])
        _mock_kf_customer(mock, "u_stranger")
        _mock_oa(mock, follower_unionids=[])
        mock.post(f"{QY}/cgi-bin/media/upload").mock(
            return_value=httpx.Response(200, json={"errcode": 0, "media_id": "QR_MID"})
        )
        send = mock.post(f"{QY}/cgi-bin/kf/send_msg").mock(
            return_value=httpx.Response(200, json={"errcode": 0, "msgid": "r1"})
        )

        await _gated_bot(client, followers, perception=perception).process_event(
            token="EVT", open_kfid="wk1"
        )

        assert [json.loads(c.request.content)["msgtype"] for c in send.calls] == ["text", "image"]
        first = json.loads(send.calls[0].request.content)["text"]["content"]
        assert "关注公众号" in first, "应该是引导关注，而不是告诉他支持哪些类型"
