"""TokenPay / TokenDance 接入：OAuth 式 API Key 授权（PKCE S256）+ 归因调用。

官方文档: https://tokendance.space/docs/api-key-oauth.md
"""

import base64
import hashlib
import secrets
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException

from ..config import get_settings


def new_pkce_pair() -> tuple[str, str]:
    """返回 (code_verifier, code_challenge)。"""
    verifier = secrets.token_urlsafe(64)[:96]
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def build_tokendance_auth_url(state: str, code_challenge: str) -> str:
    s = get_settings()
    callback = f"{s.api_base_url}/api/v1/auth/tokendance/callback?state={state}"
    params = {
        "callback_url": callback,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "app_url": s.app_url,
        "key_name": "tt2-cli",
    }
    return f"{s.tokendance_auth_url}?{urlencode(params)}"


async def exchange_tokendance_code(code: str, code_verifier: str) -> str:
    """一次性 code 换 TokenDance API Key。完整 Key 仅在此返回一次。"""
    s = get_settings()
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(
            s.tokendance_key_exchange_url,
            json={
                "code": code,
                "code_verifier": code_verifier,
                "code_challenge_method": "S256",
            },
        )
    if resp.status_code != 200:
        raise HTTPException(
            502,
            detail={
                "error": {
                    "code": "tokendance_exchange_failed",
                    "message": "TokenDance 授权码交换失败，请重新授权",
                    "details": {},
                }
            },
        )
    key = resp.json().get("key")
    if not key:
        raise HTTPException(
            502,
            detail={
                "error": {
                    "code": "tokendance_exchange_failed",
                    "message": "TokenDance 未返回 Key",
                    "details": {},
                }
            },
        )
    return key


class TokenDanceCallError(Exception):
    """模型调用失败。recovery_action 来自 TokenDance-Recovery-Action 响应头。"""

    def __init__(self, message: str, recovery_action: str | None = None) -> None:
        self.message = message
        self.recovery_action = recovery_action


async def chat_completions(
    api_key: str,
    messages: list[dict],
    tools: list[dict] | None = None,
    model: str | None = None,
) -> dict:
    """以用户的 TokenPay Key 调 TokenDance 网关（OpenAI 协议），带 X-App-URL 归因。"""
    s = get_settings()
    payload: dict = {"model": model or s.chaxunma_model, "messages": messages}
    if tools:
        payload["tools"] = tools
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{s.tokendance_base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "X-App-URL": s.app_url,
            },
            json=payload,
        )
    if resp.status_code != 200:
        recovery = resp.headers.get("TokenDance-Recovery-Action")
        raise TokenDanceCallError(
            f"TokenDance 调用失败（HTTP {resp.status_code}）", recovery_action=recovery
        )
    return resp.json()
