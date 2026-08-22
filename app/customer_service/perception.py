"""把语音/图片转成文本，再交给同一个大脑（DeepSeek）作答.

这样做而不是让多模态模型直接回复，是为了让人设和「不许编造」那套约束只有
一处——SYSTEM_PROMPT。感知层只负责"看见/听见"，不负责说话。

走阿里云百炼的 OpenAI 兼容接口：
  语音 qwen3-asr-flash  图片 qwen3-vl-flash
"""

import base64
import logging

import httpx

from ..config import settings
from .prompts import IMAGE_DESCRIBE_PROMPT

logger = logging.getLogger(__name__)


class Perception:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        api_base: str | None = None,
        asr_model: str | None = None,
        vl_model: str | None = None,
        asr_language: str | None = None,
    ) -> None:
        self._api_key = api_key if api_key is not None else settings.dashscope_api_key
        self._api_base = api_base or settings.dashscope_api_base
        self._asr_model = asr_model or settings.dashscope_asr_model
        self._vl_model = vl_model or settings.dashscope_vl_model
        self._asr_language = (
            asr_language if asr_language is not None else settings.dashscope_asr_language
        )

    async def _chat(self, payload: dict) -> str:
        # 和 DeepSeek 那条一样给 60s：识别加作答本来就串行，再久客户早走了
        async with httpx.AsyncClient(base_url=self._api_base, timeout=60.0) as http:
            resp = await http.post(
                "/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"] or ""

    async def transcribe(self, audio: bytes, *, mime: str = "audio/amr") -> str:
        """语音转文字。微信客服的语音是 AMR，qwen3-asr-flash 直接就能读."""
        data = f"data:{mime};base64,{base64.b64encode(audio).decode()}"
        # enable_itn：把口述的数字转成阿拉伯数字，客服全是单号电话，很需要
        options: dict[str, object] = {"enable_itn": True}
        if self._asr_language:
            options["language"] = self._asr_language
        return await self._chat(
            {
                "model": self._asr_model,
                "messages": [
                    {"role": "user", "content": [
                        {"type": "input_audio", "input_audio": {"data": data}},
                    ]},
                ],
                "asr_options": options,
            }
        )

    async def describe_image(self, image: bytes, *, mime: str = "image/jpeg") -> str:
        """图片转文字描述，供 DeepSeek 作答用.

        指令放在 user message 里：百炼文档明确说 VL 场景加 system message 会掉效果。
        """
        data = f"data:{mime};base64,{base64.b64encode(image).decode()}"
        return await self._chat(
            {
                "model": self._vl_model,
                "messages": [
                    {"role": "user", "content": [
                        {"type": "image_url", "image_url": {"url": data}},
                        {"type": "text", "text": IMAGE_DESCRIBE_PROMPT},
                    ]},
                ],
            }
        )
