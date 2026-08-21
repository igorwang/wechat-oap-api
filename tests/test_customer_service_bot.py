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
def bot(client):
    return SupportBot(
        client,
        api_key="ds-test-key",
        api_base=DS,
        model="deepseek-chat",
        system_prompt="你是客服",
        welcome_text="欢迎咨询",
        # 关注门禁单独测（见文件末尾），这里只关心消息收发本身
        require_unionid=False,
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
            # 非文本消息暂不回复
            {"msgid": "i1", "open_kfid": "wk1", "external_userid": "u1",
             "origin": 3, "msgtype": "image", "image": {"media_id": "MID"}},
        ])
        handled = await bot.process_event(token="EVT", open_kfid="wk1")
        assert handled == 0


# ---- 关注公众号门禁：没有 unionid 就先引导关注，不进 AI 对话 ----


def _gated_bot(client, store=None):
    return SupportBot(
        client, api_key="k", api_base=DS, system_prompt="你是客服",
        store=store, require_unionid=True,
    )


def _customer_msg(content="怎么退货？"):
    return [{
        "msgid": "m1", "open_kfid": "wk1", "external_userid": "u1",
        "origin": 3, "msgtype": "text", "text": {"content": content},
    }]


async def test_customer_without_unionid_gets_qrcode_instead_of_llm(client):
    """没关注公众号（拿不到 unionid）时不接入 AI，改发引导文案 + 二维码."""
    async with respx.mock as mock:
        _mock_qy_token(mock)
        _mock_sync(mock, _customer_msg())
        mock.post(f"{QY}/cgi-bin/kf/customer/batchget").mock(
            return_value=httpx.Response(200, json={"errcode": 0, "customer_list": [
                {"external_userid": "u1", "nickname": "小明"}  # 无 unionid
            ]})
        )
        upload = mock.post(f"{QY}/cgi-bin/media/upload").mock(
            return_value=httpx.Response(200, json={"errcode": 0, "media_id": "QR_MID"})
        )
        ds = mock.post(f"{DS}/chat/completions")
        send = mock.post(f"{QY}/cgi-bin/kf/send_msg").mock(
            return_value=httpx.Response(200, json={"errcode": 0, "msgid": "r1"})
        )

        handled = await _gated_bot(client).process_event(token="EVT", open_kfid="wk1")

        assert handled == 1
        assert not ds.called, "未关注的客户不应消耗 LLM 调用"
        assert upload.call_count == 1
        bodies = [json.loads(c.request.content) for c in send.calls]
        assert [b["msgtype"] for b in bodies] == ["text", "image"]
        assert bodies[1]["image"]["media_id"] == "QR_MID"
        assert all(b["touser"] == "u1" and b["open_kfid"] == "wk1" for b in bodies)


async def test_customer_with_unionid_reaches_llm(client):
    async with respx.mock as mock:
        _mock_qy_token(mock)
        _mock_sync(mock, _customer_msg())
        mock.post(f"{QY}/cgi-bin/kf/customer/batchget").mock(
            return_value=httpx.Response(200, json={"errcode": 0, "customer_list": [
                {"external_userid": "u1", "nickname": "小明", "unionid": "o_union_1"}
            ]})
        )
        ds = mock.post(f"{DS}/chat/completions").mock(
            return_value=httpx.Response(200, json={
                "choices": [{"message": {"content": "这个我需要帮您确认"}}]
            })
        )
        send = mock.post(f"{QY}/cgi-bin/kf/send_msg").mock(
            return_value=httpx.Response(200, json={"errcode": 0, "msgid": "r1"})
        )

        handled = await _gated_bot(client).process_event(token="EVT", open_kfid="wk1")

        assert handled == 1
        assert ds.called
        assert json.loads(send.calls.last.request.content)["text"]["content"] == "这个我需要帮您确认"


async def test_known_unionid_is_read_from_store_not_refetched(client, store):
    """库里已有 unionid 就不必每条消息都打一次 batchget."""
    await store.upsert({"external_userid": "u1", "unionid": "o_union_1"})
    async with respx.mock as mock:
        _mock_qy_token(mock)
        _mock_sync(mock, _customer_msg())
        batchget = mock.post(f"{QY}/cgi-bin/kf/customer/batchget")
        mock.post(f"{DS}/chat/completions").mock(
            return_value=httpx.Response(200, json={"choices": [{"message": {"content": "好的"}}]})
        )
        mock.post(f"{QY}/cgi-bin/kf/send_msg").mock(
            return_value=httpx.Response(200, json={"errcode": 0, "msgid": "r1"})
        )

        handled = await _gated_bot(client, store).process_event(token="EVT", open_kfid="wk1")

        assert handled == 1
        assert not batchget.called


async def test_qrcode_media_id_is_reused_across_messages(client):
    """临时素材 3 天有效，不该每条消息都重传一次二维码."""
    async with respx.mock as mock:
        _mock_qy_token(mock)
        _mock_sync(mock, [
            {"msgid": "m1", "open_kfid": "wk1", "external_userid": "u1",
             "origin": 3, "msgtype": "text", "text": {"content": "在吗"}},
            {"msgid": "m2", "open_kfid": "wk1", "external_userid": "u1",
             "origin": 3, "msgtype": "text", "text": {"content": "有人吗"}},
        ])
        mock.post(f"{QY}/cgi-bin/kf/customer/batchget").mock(
            return_value=httpx.Response(200, json={"errcode": 0, "customer_list": [
                {"external_userid": "u1"}
            ]})
        )
        upload = mock.post(f"{QY}/cgi-bin/media/upload").mock(
            return_value=httpx.Response(200, json={"errcode": 0, "media_id": "QR_MID"})
        )
        mock.post(f"{QY}/cgi-bin/kf/send_msg").mock(
            return_value=httpx.Response(200, json={"errcode": 0, "msgid": "r1"})
        )

        assert await _gated_bot(client).process_event(token="EVT", open_kfid="wk1") == 2
        assert upload.call_count == 1
