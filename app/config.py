from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    wechat_appid: str = ""
    wechat_appsecret: str = ""
    wechat_api_base: str = "https://api.weixin.qq.com"
    wechat_token_cache_path: str = ".wechat_token.json"
    # 公众号消息推送回调（微信开发者平台 → 公众号 → 基础信息 → 域名与消息推送配置）
    # 回调 URL: https://<域名>/wechat/callback，消息加密选「安全模式」
    wechat_callback_token: str = ""
    wechat_aes_key: str = ""
    api_key: str = ""
    api_key_header: str = "X-API-Key"

    # 微信客服 (WeChat Customer Service) — 独立于公众号的凭证体系
    cs_corpid: str = ""
    cs_secret: str = ""
    cs_api_base: str = "https://qyapi.weixin.qq.com"
    cs_callback_token: str = ""
    cs_aes_key: str = ""
    cs_cursor_path: str = ".cs_cursor.json"
    # PostgreSQL，形如 postgresql+asyncpg://user:pass@host:5432/db
    # 留空则不落库（机器人仍可正常收发消息）
    database_url: str = ""
    cs_welcome_text: str = "您好，我是智能客服斐恩(Feyn)，请问有什么可以帮您？"
    # 未关注公众号的客户只收到引导关注的二维码，不接入 AI（判据取自公众号关注者名单）
    cs_require_follow: bool = True

    # DeepSeek — 机器人回复所用 LLM
    deepseek_api_key: str = ""
    deepseek_api_base: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"

    # 阿里云百炼 DashScope — 图片理解 / 语音识别（OpenAI 兼容接口）
    dashscope_api_key: str = ""
    dashscope_api_base: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    dashscope_vl_model: str = "qwen3-vl-flash"
    dashscope_asr_model: str = "qwen3-asr-flash"
    host: str = "0.0.0.0"
    port: int = 8000


settings = Settings()
