"""控制台会话 Cookie（itsdangerous 签名）。"""

from itsdangerous import BadSignature, URLSafeSerializer

from ..config import get_settings


def _serializer() -> URLSafeSerializer:
    return URLSafeSerializer(get_settings().session_secret, salt="tt2-console")


def sign_session(user_id: int) -> str:
    return _serializer().dumps({"uid": user_id})


def unsign_session(value: str) -> int | None:
    try:
        data = _serializer().loads(value)
    except BadSignature:
        return None
    uid = data.get("uid")
    return int(uid) if isinstance(uid, int) else None
