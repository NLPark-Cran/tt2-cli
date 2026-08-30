"""FastAPI 依赖：Redis、当前用户（CLI Bearer Token 或控制台会话 Cookie）。"""

from datetime import UTC, datetime

import redis.asyncio as aioredis
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_settings
from .core.security import hash_token
from .db import get_db
from .models import CliToken, User

_redis: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(get_settings().redis_url, decode_responses=True)
    return _redis


def _unauthorized(msg: str = "未认证或凭证已失效") -> HTTPException:
    return HTTPException(
        401, detail={"error": {"code": "unauthorized", "message": msg, "details": {}}}
    )


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    """CLI：Authorization: Bearer tt2_pat_...；控制台：tt2_session Cookie（user_id）。"""
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        token_hash = hash_token(auth.removeprefix("Bearer ").strip())
        row = (
            await db.execute(
                select(CliToken, User)
                .join(User, User.id == CliToken.user_id)
                .where(CliToken.token_hash == token_hash, CliToken.revoked_at.is_(None))
            )
        ).first()
        if not row:
            raise _unauthorized()
        token, user = row
        token.last_used_at = datetime.now(UTC)
        await db.commit()
        return user

    session_cookie = request.cookies.get("tt2_session")
    if session_cookie:
        from .core.session import unsign_session

        user_id = unsign_session(session_cookie)
        if user_id:
            user = await db.get(User, user_id)
            if user:
                return user
    raise _unauthorized()
