"""认证：观猹 OAuth 登录、设备码授权流、TokenPay（TokenDance）连接。"""

import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, RedirectResponse
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..core.errors import err
from ..core.security import (
    encrypt_secret,
    new_cli_token,
    new_device_code,
)
from ..core.session import sign_session
from ..db import get_db
from ..deps import get_current_user, get_redis
from ..models import CliToken, DeviceCode, TokenDanceKey, User
from ..schemas import DeviceCodeOut, MeOut
from ..services import tokendance, watcha

router = APIRouter(prefix="/auth", tags=["auth"])


# ---------- 观猹 OAuth（控制台登录） ----------


@router.get("/watcha/login")
async def watcha_login(redis: Redis = Depends(get_redis)) -> RedirectResponse:
    state = secrets.token_urlsafe(16)
    await redis.set(f"oauth:watcha:{state}", "1", ex=600)
    return RedirectResponse(watcha.build_authorize_url(state))


@router.get("/watcha/callback")
async def watcha_callback(
    code: str = Query(default=""),
    state: str = Query(default=""),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> RedirectResponse:
    if not code or not state or not await redis.delete(f"oauth:watcha:{state}"):
        raise err(400, "bad_oauth_state", "授权状态无效或已过期")
    token_data = await watcha.exchange_code(code)
    info = await watcha.fetch_userinfo(token_data["access_token"])

    user = (
        (await db.execute(select(User).where(User.watcha_user_id == info["user_id"])))
        .scalars()
        .first()
    )
    if not user:
        user = User(
            watcha_user_id=info["user_id"],
            nickname=info.get("nickname") or "猹友",
            avatar_url=info.get("avatar_url") or "",
            email=info.get("email"),
        )
        db.add(user)
    else:
        user.nickname = info.get("nickname") or user.nickname
        user.avatar_url = info.get("avatar_url") or user.avatar_url
    await db.commit()

    resp = RedirectResponse(f"{get_settings().web_base_url}/console")
    resp.set_cookie(
        "tt2_session",
        sign_session(user.id),
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=30 * 86400,
    )
    return resp


@router.post("/logout")
async def logout() -> JSONResponse:
    resp = JSONResponse({"ok": True})
    resp.delete_cookie("tt2_session")
    return resp


@router.get("/me", response_model=MeOut)
async def me(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MeOut:
    key = (
        (
            await db.execute(
                select(TokenDanceKey).where(
                    TokenDanceKey.user_id == user.id, TokenDanceKey.active.is_(True)
                )
            )
        )
        .scalars()
        .first()
    )
    return MeOut(
        nickname=user.nickname,
        avatar_url=user.avatar_url,
        tokendance_connected=key is not None,
    )


# ---------- 设备码授权流（CLI 登录） ----------


@router.post("/device", response_model=DeviceCodeOut)
async def device_start(db: AsyncSession = Depends(get_db)) -> DeviceCodeOut:
    device_code, user_code = new_device_code()
    dc = DeviceCode(
        device_code=device_code,
        user_code=user_code,
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
    )
    db.add(dc)
    await db.commit()
    base = get_settings().web_base_url
    return DeviceCodeOut(
        device_code=device_code,
        user_code=user_code,
        verification_url=f"{base}/console/device?code={user_code}",
        expires_in=600,
    )


@router.get("/device/poll")
async def device_poll(
    device_code: str = Query(min_length=10),
    db: AsyncSession = Depends(get_db),
) -> dict:
    dc = (
        (await db.execute(select(DeviceCode).where(DeviceCode.device_code == device_code)))
        .scalars()
        .first()
    )
    if not dc or dc.expires_at < datetime.now(UTC):
        raise err(410, "device_expired", "设备码已过期，请重新 login")
    if dc.status == "denied":
        raise err(403, "device_denied", "用户拒绝了授权")
    if dc.status != "approved" or not dc.cli_token_id:
        return {"status": "pending"}
    token_row = await db.get(CliToken, dc.cli_token_id)
    if not token_row:
        raise err(500, "internal_error", "令牌不存在")
    # 明文 token 由 approve 时暂存 Redis（10 分钟），此处取出后即焚
    redis = get_redis()
    plain = await redis.getdel(f"device:token:{dc.device_code}")
    if not plain:
        raise err(410, "device_expired", "令牌已领取或已过期")
    return {"status": "approved", "token": plain}


@router.post("/device/approve")
async def device_approve(
    user_code: str = Query(min_length=4),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> dict:
    dc = (
        (
            await db.execute(
                select(DeviceCode).where(
                    DeviceCode.user_code == user_code.upper(),
                    DeviceCode.status == "pending",
                )
            )
        )
        .scalars()
        .first()
    )
    if not dc or dc.expires_at < datetime.now(UTC):
        raise err(404, "device_not_found", "设备码不存在或已过期")
    plain, token_hash, prefix = new_cli_token()
    token_row = CliToken(
        user_id=user.id, name=f"device-{dc.user_code}", prefix=prefix, token_hash=token_hash
    )
    db.add(token_row)
    await db.flush()
    dc.status = "approved"
    dc.user_id = user.id
    dc.cli_token_id = token_row.id
    await db.commit()
    await redis.set(f"device:token:{dc.device_code}", plain, ex=600)
    return {"ok": True}


# ---------- TokenPay（TokenDance OAuth 式 Key 授权） ----------


@router.get("/tokendance/connect")
async def tokendance_connect(
    user: User = Depends(get_current_user),
    redis: Redis = Depends(get_redis),
) -> dict:
    verifier, challenge = tokendance.new_pkce_pair()
    state = secrets.token_urlsafe(16)
    await redis.set(f"oauth:td:{state}", f"{user.id}:{verifier}", ex=600)
    return {"authorize_url": tokendance.build_tokendance_auth_url(state, challenge)}


@router.get("/tokendance/callback")
async def tokendance_callback(
    code: str = Query(min_length=1),
    state: str = Query(min_length=1),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> RedirectResponse:
    saved = await redis.getdel(f"oauth:td:{state}")
    if not saved or ":" not in saved:
        raise err(400, "bad_oauth_state", "授权状态无效或已过期")
    user_id_str, verifier = saved.split(":", 1)
    api_key = await tokendance.exchange_tokendance_code(code, verifier)

    user_id = int(user_id_str)
    # 每用户只保留一条有效 Key：旧的置为失效
    old_keys = (
        (
            await db.execute(
                select(TokenDanceKey).where(
                    TokenDanceKey.user_id == user_id, TokenDanceKey.active.is_(True)
                )
            )
        )
        .scalars()
        .all()
    )
    for k in old_keys:
        k.active = False
    db.add(
        TokenDanceKey(
            user_id=user_id,
            key_enc=encrypt_secret(api_key),
            key_prefix=api_key[:8],
        )
    )
    await db.commit()
    return RedirectResponse(f"{get_settings().web_base_url}/console?tokendance=connected")
