"""安全相关工具：哈希、加密、ID 生成。"""

import hashlib
import secrets
import time

from cryptography.fernet import Fernet

from ..config import get_settings

TOKEN_PREFIX = "tt2_pat_"  # noqa: S105 令牌前缀而非口令


def new_cli_token() -> tuple[str, str, str]:
    """返回 (明文 token, sha256 哈希, 展示前缀)。明文只出现一次。"""
    raw = secrets.token_urlsafe(32)
    token = f"{TOKEN_PREFIX}{raw}"
    return token, hash_token(token), token[:16]


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_task_id() -> str:
    # 时间序 + 随机，便于按时间排序
    return f"t{int(time.time() * 1000):013x}{secrets.token_hex(5)}"


def new_device_code() -> tuple[str, str]:
    device_code = secrets.token_urlsafe(24)
    user_code = f"{secrets.token_hex(2)}-{secrets.token_hex(2)}".upper()
    return device_code, user_code


_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        key = get_settings().fernet_key
        if not key:
            raise RuntimeError("TT2_FERNET_KEY 未配置")
        _fernet = Fernet(key.encode())
    return _fernet


def encrypt_secret(plain: str) -> str:
    return _get_fernet().encrypt(plain.encode()).decode()


def decrypt_secret(enc: str) -> str:
    return _get_fernet().decrypt(enc.encode()).decode()
