from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    wechat_appid: str = ""
    wechat_appsecret: str = ""
    wechat_api_base: str = "https://api.weixin.qq.com"
    wechat_token_cache_path: str = ".wechat_token.json"
    api_key: str = ""
    api_key_header: str = "X-API-Key"
    host: str = "0.0.0.0"
    port: int = 8000


settings = Settings()
