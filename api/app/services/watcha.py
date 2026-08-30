"""观猹 OAuth2 客户端。"""

from urllib.parse import urlencode

import httpx
from fastapi import HTTPException

from ..config import get_settings


def build_authorize_url(state: str) -> str:
    s = get_settings()
    params = {
        "response_type": "code",
        "client_id": s.watcha_client_id,
        "redirect_uri": f"{s.api_base_url}/api/v1/auth/watcha/callback",
        "scope": "read",
        "state": state,
    }
    # client_id 可能含 +/= 等特殊字符，urlencode 默认已处理
    return f"{s.watcha_authorize_url}?{urlencode(params)}"


async def exchange_code(code: str) -> dict:
    s = get_settings()
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            s.watcha_token_url,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": f"{s.api_base_url}/api/v1/auth/watcha/callback",
                "client_id": s.watcha_client_id,
                "client_secret": s.watcha_client_secret,
            },
        )
    data = resp.json()
    if resp.status_code != 200 or "access_token" not in data:
        raise HTTPException(
            502,
            detail={
                "error": {
                    "code": "watcha_token_failed",
                    "message": "观猹授权码换取 Token 失败",
                    "details": {},
                }
            },
        )
    return data


async def fetch_userinfo(access_token: str) -> dict:
    s = get_settings()
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(s.watcha_userinfo_url, params={"access_token": access_token})
    data = resp.json()
    if data.get("statusCode") != 200:
        raise HTTPException(
            502,
            detail={
                "error": {
                    "code": "watcha_userinfo_failed",
                    "message": "获取观猹用户信息失败",
                    "details": {},
                }
            },
        )
    return data["data"]
