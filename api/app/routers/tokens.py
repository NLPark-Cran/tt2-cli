"""CLI Token 管理（控制台会话）。"""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.errors import err
from ..core.security import new_cli_token
from ..db import get_db
from ..deps import get_current_user
from ..models import CliToken, User
from ..schemas import TokenCreated, TokenOut

router = APIRouter(prefix="/tokens", tags=["tokens"])


@router.get("", response_model=list[TokenOut])
async def list_tokens(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[TokenOut]:
    rows = (
        (
            await db.execute(
                select(CliToken).where(CliToken.user_id == user.id, CliToken.revoked_at.is_(None))
            )
        )
        .scalars()
        .all()
    )
    return [
        TokenOut(name=t.name, prefix=t.prefix, created_at=t.created_at, last_used_at=t.last_used_at)
        for t in rows
    ]


@router.post("", response_model=TokenCreated)
async def create_token(
    name: str = "manual",
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TokenCreated:
    plain, token_hash, prefix = new_cli_token()
    db.add(CliToken(user_id=user.id, name=name[:64], prefix=prefix, token_hash=token_hash))
    await db.commit()
    return TokenCreated(token=plain, name=name[:64], prefix=prefix)


@router.delete("/{prefix}")
async def revoke_token(
    prefix: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from datetime import UTC, datetime

    row = (
        (
            await db.execute(
                select(CliToken).where(
                    CliToken.user_id == user.id,
                    CliToken.prefix == prefix,
                    CliToken.revoked_at.is_(None),
                )
            )
        )
        .scalars()
        .first()
    )
    if not row:
        raise err(404, "token_not_found", "令牌不存在")
    row.revoked_at = datetime.now(UTC)
    await db.commit()
    return {"ok": True}
