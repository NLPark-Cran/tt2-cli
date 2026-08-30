"""安全工具：token 哈希、Fernet 加解密、会话签名。"""

from app.core.security import (
    decrypt_secret,
    encrypt_secret,
    hash_token,
    new_cli_token,
    new_device_code,
    new_task_id,
)
from app.core.session import sign_session, unsign_session


def test_cli_token():
    plain, hashed, prefix = new_cli_token()
    assert plain.startswith("tt2_pat_")
    assert hash_token(plain) == hashed
    assert plain[:16] == prefix
    assert plain not in hashed


def test_fernet_roundtrip():
    enc = encrypt_secret("sk-test-key")
    assert "sk-test-key" not in enc
    assert decrypt_secret(enc) == "sk-test-key"


def test_session_sign():
    value = sign_session(42)
    assert unsign_session(value) == 42
    assert unsign_session(value + "tampered") is None
    assert unsign_session("garbage") is None


def test_ids():
    assert new_task_id() != new_task_id()
    dc, uc = new_device_code()
    assert len(dc) > 20 and "-" in uc
