"""微信客服回调的签名校验与 AES 加解密（企业微信 WXBizMsgCrypt 方案）."""

import base64
import hashlib
import hmac
import struct

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


class InvalidSignature(ValueError):
    """msg_signature 与内容不匹配：来源不可信或内容被篡改."""


class CallbackCrypto:
    def __init__(self, token: str, aes_key: str, receive_id: str):
        self._token = token
        self._key = base64.b64decode(aes_key + "=")
        if len(self._key) != 32:
            raise ValueError("EncodingAESKey must decode to 32 bytes (43 chars)")
        self._iv = self._key[:16]
        self._receive_id = receive_id

    def _signature(self, timestamp: str, nonce: str, encrypted: str) -> str:
        raw = "".join(sorted([self._token, timestamp, nonce, encrypted]))
        return hashlib.sha1(raw.encode()).hexdigest()

    def _decrypt(self, encrypted: str) -> str:
        cipher = Cipher(algorithms.AES(self._key), modes.CBC(self._iv)).decryptor()
        padded = cipher.update(base64.b64decode(encrypted)) + cipher.finalize()
        plain = padded[: -padded[-1]]
        # 16 bytes random | 4 bytes msg length (network order) | msg | receive_id
        (msg_len,) = struct.unpack("!I", plain[16:20])
        msg = plain[20 : 20 + msg_len]
        receive_id = plain[20 + msg_len :].decode()
        if receive_id != self._receive_id:
            raise ValueError(f"receive_id mismatch: {receive_id!r}")
        return msg.decode()

    def _verify(self, msg_signature: str, timestamp: str, nonce: str, encrypted: str) -> None:
        expected = self._signature(timestamp, nonce, encrypted)
        if not hmac.compare_digest(expected, msg_signature):
            raise InvalidSignature("msg_signature mismatch")

    def verify_plain_signature(self, signature: str, timestamp: str, nonce: str) -> None:
        """公众号 URL 验证的签名：只由 token/timestamp/nonce 三者算出，不含 echostr.

        企业微信那套（verify_url）把加密后的 echostr 也拌进签名并要求解密回显，
        公众号不是——echostr 原样返回即可。
        """
        raw = "".join(sorted([self._token, timestamp, nonce]))
        expected = hashlib.sha1(raw.encode()).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise InvalidSignature("signature mismatch")

    def verify_url(self, msg_signature: str, timestamp: str, nonce: str, echostr: str) -> str:
        """GET 回调校验：验签并返回解密后的 echostr 明文."""
        self._verify(msg_signature, timestamp, nonce, echostr)
        return self._decrypt(echostr)

    def decrypt_message(
        self, msg_signature: str, timestamp: str, nonce: str, encrypted: str
    ) -> str:
        """POST 回调：验签并返回解密后的 XML 明文."""
        self._verify(msg_signature, timestamp, nonce, encrypted)
        return self._decrypt(encrypted)
