from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    wechat_appid: str = ""
    wechat_appsecret: str = ""
    wechat_api_base: str = "https://api.weixin.qq.com"
    wechat_token_cache_path: str = ".wechat_token.json"
    api_key: str = ""
    api_key_header: str = "X-API-Key"

    # 微信客服 (WeChat Customer Service) — 独立于公众号的凭证体系
    cs_corpid: str = ""
    cs_secret: str = ""
    cs_api_base: str = "https://qyapi.weixin.qq.com"
    cs_callback_token: str = ""
    cs_aes_key: str = ""
    cs_cursor_path: str = ".cs_cursor.json"
    cs_welcome_text: str = "您好，我是智能客服助手，请问有什么可以帮您？"

    # DeepSeek — 机器人回复所用 LLM
    deepseek_api_key: str = ""
    deepseek_api_base: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    deepseek_system_prompt: str = "你是一名专业、友善的客服助手，用简体中文简洁地回答客户问题。"
    host: str = "0.0.0.0"
    port: int = 8000


settings = Settings()
