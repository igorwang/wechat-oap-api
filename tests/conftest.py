import os

os.environ.setdefault("WECHAT_APPID", "test_appid")
os.environ.setdefault("WECHAT_APPSECRET", "test_secret")
# Disable file token cache for tests by default; individual tests can override.
os.environ["WECHAT_TOKEN_CACHE_PATH"] = ""

import pytest

from app.wechat import WeChatClient


@pytest.fixture
def fresh_client():
    """A clean WeChatClient instance per test, no file cache."""
    c = WeChatClient(cache_path="")
    yield c


@pytest.fixture(autouse=True)
def reset_global_client():
    """Reset the module-level singleton's cache between tests."""
    from app import wechat

    wechat.wechat_client._token = None
    wechat.wechat_client._token_expiry = 0.0
    yield
    wechat.wechat_client._token = None
    wechat.wechat_client._token_expiry = 0.0
