import os

# Never use live credentials, a production database or startup follower sync in tests.
os.environ["WECHAT_APPID"] = "test_appid"
os.environ["WECHAT_APPSECRET"] = "test_secret"
os.environ["API_KEY"] = ""
os.environ["DATABASE_URL"] = ""
os.environ["CS_REQUIRE_FOLLOW"] = "false"
os.environ["CS_GROUP_QR_OPEN_KFID"] = ""
os.environ["CS_GROUP_QR_PATH"] = ""
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
