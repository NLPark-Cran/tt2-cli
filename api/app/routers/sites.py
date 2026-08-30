"""站点管理。"""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.errors import err
from ..db import get_db
from ..deps import get_current_user
from ..models import Site, User
from ..schemas import SiteOut
from ..services.deployer import remove_site_from_node

router = APIRouter(prefix="/sites", tags=["sites"])


def _site_out(s: Site) -> SiteOut:
    return SiteOut(
        name=s.name,
        host=s.host,
        url=f"https://{s.host}",
        spa=s.spa,
        status=s.status,
        created_at=s.created_at,
    )


@router.get("", response_model=list[SiteOut])
async def list_sites(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[SiteOut]:
    rows = (
        (await db.execute(select(Site).where(Site.user_id == user.id, Site.status == "active")))
        .scalars()
        .all()
    )
    return [_site_out(s) for s in rows]


@router.delete("/{name}")
async def delete_site(
    name: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    site = (
        (
            await db.execute(
                select(Site).where(
                    Site.name == name, Site.user_id == user.id, Site.status == "active"
                )
            )
        )
        .scalars()
        .first()
    )
    if not site:
        raise err(404, "site_not_found", "站点不存在")
    await site.awaitable_attrs.node  # noqa: B018 — 触发懒加载
    await remove_site_from_node(site, site.node)
    site.status = "deleted"
    await db.commit()
    return {"ok": True}
