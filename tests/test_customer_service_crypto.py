"""CallbackCrypto — 微信客服回调的签名校验与 AES 解密.

真值向量由独立参考实现按企业微信官方算法规范预计算（见文档「回调配置」），
不依赖被测代码。
"""

import pytest

from app.customer_service.crypto import CallbackCrypto, InvalidSignature

TOKEN = "TestCallbackToken"
AES_KEY = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQ"
CORPID = "ww1234567890abcdef"

TS = "1700000000"
NONCE = "nonce123"

ECHO_PLAIN = "8964103459665061180"
ECHO_ENC = "B4PcXgtThYsrOQnzxvXRUD3gwtL07Jdvp+c3FmjtNAUkrYBM5aBTCQfxoHEdguAy8zQrV4vNxW0PsT12iAQCTw=="
ECHO_SIG = "13bc594fc5cfa86b8141f09a5560463e19b01b22"

EVENT_XML = (
    "<xml><ToUserName><![CDATA[ww1234567890abcdef]]></ToUserName>"
    "<CreateTime>1348831860</CreateTime><MsgType><![CDATA[event]]></MsgType>"
    "<Event><![CDATA[kf_msg_or_event]]></Event>"
    "<Token><![CDATA[ENCSyncToken123]]></Token>"
    "<OpenKfId><![CDATA[wkAJ2GCAAA_test]]></OpenKfId></xml>"
)
EVENT_ENC = (
    "B4PcXgtThYsrOQnzxvXRUJpbfQleP/DOOYPU6TX8a7Rae8eLZXP0as9yIjyUaw4HvDP47ckPJ/n79uD9atGcN7"
    "MF4uSmg+7JHZglBcfRVe+Jaon48Tl48g9XQwPERiGRek69Uad440FGS6xt3wnf5rlxgUfBJRA9SirgRNQkItA+"
    "xtr5aTW5YRV+5d3OQE2rijE4anY+PIQZ95eM7kgOyblaLDP6sZaKqh5xiSe+PlidwtCubRQoyOxrGQCFHQ4hoy"
    "eQ8BbHh0EkYMLeo6X5R59h11SDk6mFw0aDk5SmuFvh8/tfgRuNHKgoxNlJLJ6veS80Lsp3Hg7JgFBm7Z4xunEo"
    "SCXBE8qT7g4R/mpMBicHIfado8TMqTltDOggFMaeG5RcEyExq0uY0mLiLCRnkyOsisnKDPpcczP9rG7raRg="
)
EVENT_SIG = "5bf7ad4143f1caa0d89d0c20d9f35906ad6debb7"


@pytest.fixture
def crypto():
    return CallbackCrypto(token=TOKEN, aes_key=AES_KEY, receive_id=CORPID)


def test_verify_url_returns_decrypted_echostr(crypto):
    assert crypto.verify_url(ECHO_SIG, TS, NONCE, ECHO_ENC) == ECHO_PLAIN


def test_verify_url_rejects_bad_signature(crypto):
    with pytest.raises(InvalidSignature):
        crypto.verify_url("0" * 40, TS, NONCE, ECHO_ENC)


def test_decrypt_message_returns_plaintext_xml(crypto):
    assert crypto.decrypt_message(EVENT_SIG, TS, NONCE, EVENT_ENC) == EVENT_XML


def test_decrypt_message_rejects_tampered_ciphertext(crypto):
    tampered = EVENT_ENC[:-8] + "AAAAAAA="
    with pytest.raises(InvalidSignature):
        crypto.decrypt_message(EVENT_SIG, TS, NONCE, tampered)


def test_decrypt_message_rejects_wrong_receive_id():
    other = CallbackCrypto(token=TOKEN, aes_key=AES_KEY, receive_id="ww_other_corp")
    with pytest.raises(ValueError):
        other.decrypt_message(EVENT_SIG, TS, NONCE, EVENT_ENC)
