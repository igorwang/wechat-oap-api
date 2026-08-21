"""SupportBot — 回调事件驱动的机器人编排：拉取消息 → DeepSeek 生成 → 客服回复."""

import json

import httpx
import pytest
import respx

from app.customer_service.bot import SupportBot
from app.customer_service.client import CustomerServiceClient

QY = "https://qyapi.weixin.qq.com"
DS = "https://api.deepseek.com"


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
