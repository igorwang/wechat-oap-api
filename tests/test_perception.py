"""Perception — 把语音/图片转成文本，交给同一个大脑处理.

语音走 qwen3-asr-flash、图片走 qwen3-vl-flash，都是百炼的 OpenAI 兼容接口。
契约是拿真号打通过的：AMR 直接喂给 ASR 就能转写（微信客服 sync_msg 的
voice_format=0 就是 AMR），不需要 ffmpeg 转码。
"""

import base64
import json

import httpx
import respx

from app.customer_service.perception import Perception

DASH = "https://dashscope.aliyuncs.com/compatible-mode/v1"

AMR = b"#!AMR\n" + (b"\x04" + b"\x00" * 12) * 50
JPEG = b"\xff\xd8\xff\xe0" + b"fake jpeg bytes"


def _perception(**kwargs):
    return Perception(api_key="dash-test-key", api_base=DASH, **kwargs)


def _mock_reply(mock, content):
    return mock.post(f"{DASH}/chat/completions").mock(
        return_value=httpx.Response(
            200, json={"choices": [{"message": {"role": "assistant", "content": content}}]}
        )
    )


async def test_transcribe_returns_the_recognised_text():
    async with respx.mock as mock:
        route = _mock_reply(mock, "你好，我想问一下你们的退货政策")

        text = await _perception(asr_model="qwen3-asr-flash").transcribe(AMR)

        assert text == "你好，我想问一下你们的退货政策"
        body = json.loads(route.calls.last.request.content)
        assert body["model"] == "qwen3-asr-flash"
        part = body["messages"][0]["content"][0]
        assert part["type"] == "input_audio"
        assert part["input_audio"]["data"] == (
            "data:audio/amr;base64," + base64.b64encode(AMR).decode()
        )
        assert route.calls.last.request.headers["authorization"] == "Bearer dash-test-key"


async def test_transcribe_asks_for_digits_not_spelled_out_numbers():
    """客服场景全是单号、电话，enable_itn 让「一二三」转成 123."""
    async with respx.mock as mock:
        route = _mock_reply(mock, "我的单号是 20260821")

        await _perception(asr_language="zh").transcribe(AMR)

        options = json.loads(route.calls.last.request.content)["asr_options"]
        assert options["enable_itn"] is True
        assert options["language"] == "zh"


async def test_blank_asr_language_lets_the_model_auto_detect():
    """留空要让模型自己判语种，而不是发一个空字符串把识别带偏."""
    async with respx.mock as mock:
        route = _mock_reply(mock, "hello")

        await _perception(asr_language="").transcribe(AMR)

        assert "language" not in json.loads(route.calls.last.request.content)["asr_options"]


async def test_describe_image_returns_what_the_model_sees():
    async with respx.mock as mock:
        route = _mock_reply(mock, "一张订单截图，显示订单号 20260821，状态『已发货』")

        described = await _perception(vl_model="qwen3-vl-flash").describe_image(JPEG)

        assert described == "一张订单截图，显示订单号 20260821，状态『已发货』"
        body = json.loads(route.calls.last.request.content)
        assert body["model"] == "qwen3-vl-flash"
        parts = body["messages"][0]["content"]
        image = next(p for p in parts if p["type"] == "image_url")
        assert image["image_url"]["url"] == (
            "data:image/jpeg;base64," + base64.b64encode(JPEG).decode()
        )
        # 描述指令必须走 user message：百炼文档说 VL 场景加 system message 会掉效果
        assert any(p["type"] == "text" for p in parts)
        assert not any(m["role"] == "system" for m in body["messages"])


async def test_describe_image_honours_the_actual_content_type():
    """媒体下载回来什么类型就标什么，png 标成 jpeg 有的模型会拒."""
    async with respx.mock as mock:
        route = _mock_reply(mock, "一张图")

        await _perception().describe_image(b"\x89PNG\r\n", mime="image/png")

        parts = json.loads(route.calls.last.request.content)["messages"][0]["content"]
        image = next(p for p in parts if p["type"] == "image_url")
        assert image["image_url"]["url"].startswith("data:image/png;base64,")
