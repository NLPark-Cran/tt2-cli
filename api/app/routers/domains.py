"""自备域名接入：添加、DNS 指南、解析检查、删除。"""

import asyncio

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.errors import err
from ..core.logging import get_logger
from ..core.validators import validate_domain
from ..db import get_db
from ..deps import get_current_user
from ..models import Domain, Site, User
from ..schemas import DomainIn, DomainOut

log = get_logger("domains")

router = APIRouter(prefix="/domains", tags=["domains"])


def dns_guide(domain: str, site_host: str, node_ip: str) -> dict:
    return {
        "recommended": {
            "type": "CNAME",
            "host": domain.split(".")[0] if domain.count(".") > 1 else "@",
            "value": site_host,
            "note": "推荐。CNAME 到平台域名，后续节点迁移无需改动。",
        },
        "alternative": {
            "type": "A",
            "host": "@ 或子域名前缀",
            "value": node_ip,
            "note": "根域名（如 88sj.com）无法 CNAME 时使用 A 记录直连节点 IP。",
        },
        "providers": {
            "阿里云": f"控制台 → 域名 → 解析 → 添加记录：类型 CNAME，记录值填 {site_host}",
            "腾讯云DNSPod": f"DNSPod → 记录管理 → 添加记录：类型 CNAME，记录值填 {site_host}",
            "Cloudflare": f"DNS → Records → Add：Type CNAME，Target 填 {site_host}（代理可开可关）",
        },
        "ttl": "600（或默认）",
        "after": "保存后运行 `tt2 domain check " + domain + "`，解析生效后 HTTPS 证书将自动签发。",
    }


async def _resolve_ip(domain: str) -> str | None:
    proc = await asyncio.create_subprocess_exec(
        "getent",
        "ahostsv4",
        domain,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    out, _ = await proc.communicate()
    if proc.returncode != 0 or not out:
        return None
    return out.decode().split()[0]


@router.post("", response_model=DomainOut, status_code=201)
async def add_domain(
    body: DomainIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DomainOut:
    domain = validate_domain(body.domain)
    site = (
        (
            await db.execute(
                select(Site).where(
                    Site.name == body.site, Site.user_id == user.id, Site.status == "active"
                )
            )
        )
        .scalars()
        .first()
    )
    if not site:
        raise err(404, "site_not_found", "站点不存在")
    exists = (await db.execute(select(Domain).where(Domain.domain == domain))).scalars().first()
    if exists:
        raise err(409, "domain_taken", "该域名已被绑定")

    await site.awaitable_attrs.node
    row = Domain(site_id=site.id, domain=domain)
    db.add(row)
    await db.commit()
    return DomainOut(
        domain=domain,
        status=row.status,
        site=site.name,
        dns_guide=dns_guide(domain, site.host, site.node.ip),
    )


@router.get("", response_model=list[DomainOut])
async def list_domains(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[DomainOut]:
    rows = (
        await db.execute(
            select(Domain, Site)
            .join(Site, Site.id == Domain.site_id)
            .where(Site.user_id == user.id, Site.status == "active")
        )
    ).all()
    out = []
    for d, s in rows:
        await s.awaitable_attrs.node
        out.append(
            DomainOut(
                domain=d.domain,
                status=d.status,
                site=s.name,
                dns_guide=dns_guide(d.domain, s.host, s.node.ip),
            )
        )
    return out


@router.get("/{domain}/check")
async def check_domain(
    domain: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    domain = validate_domain(domain)
    row = (await db.execute(select(Domain).where(Domain.domain == domain))).scalars().first()
    if not row:
        raise err(404, "domain_not_found", "请先添加该域名")
    site = await db.get(Site, row.site_id)
    if not site or site.user_id != user.id:
        raise err(403, "forbidden", "无权操作")
    await site.awaitable_attrs.node
    ip = await _resolve_ip(domain)
    ok = ip == site.node.ip
    if ok and row.status != "active":
        row.status = "active"
        await db.commit()
        from ..services.deployer import sync_site_domains

        try:
            await sync_site_domains(db, site)
        except Exception:  # noqa: BLE001
            log.awarning("caddy_sync_failed", domain=domain)  # 下次部署会重建
    return {
        "domain": domain,
        "resolved_ip": ip,
        "expected_ip": site.node.ip,
        "dns_ok": ok,
        "status": row.status,
        "hint": "解析已生效，HTTPS 证书将在首次访问后数秒内自动签发。"
        if ok
        else "解析尚未生效，请按 dns_guide 检查记录；DNS 生效可能需要几分钟。",
    }


@router.delete("/{domain}")
async def delete_domain(
    domain: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    domain = validate_domain(domain)
    rows = (
        await db.execute(
            select(Domain, Site)
            .join(Site, Site.id == Domain.site_id)
            .where(Domain.domain == domain, Site.user_id == user.id)
        )
    ).first()
    if not rows:
        raise err(404, "domain_not_found", "域名不存在")
    d, _ = rows
    await db.delete(d)
    await db.commit()
    return {"ok": True}
