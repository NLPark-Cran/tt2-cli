"""部署执行器：暂存区 → 边缘节点（rsync + Caddy 片段 + reload + 回探）。

安全模型：控制面只通过 SSH 以低权 deploy 用户推送；Caddy 片段安装与 reload
由节点上的固定脚本 /usr/local/bin/tt2-caddy-install 完成（sudoers 白名单）。
"""

import asyncio
import shutil
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..core.logging import get_logger
from ..models import Node, Site

log = get_logger("deployer")

SSH_KEY = "/etc/tt2/deploy_key"
SSH_OPTS = [
    "-i",
    SSH_KEY,
    "-o",
    "StrictHostKeyChecking=accept-new",
    "-o",
    "ConnectTimeout=10",
    "-o",
    "BatchMode=yes",
]

CACHE_EXTENSIONS = (
    "css|js|mjs|png|jpg|jpeg|gif|webp|avif|svg|ico|woff|woff2|ttf|otf|mp3|mp4|webm|wasm"
)


def render_caddy_snippet(primary_host: str, extra_hosts: list[str], spa: bool) -> str:
    addresses = ", ".join([primary_host, *extra_hosts])
    spa_block = ""
    if spa:
        spa_block = """
    @spa_not_found {
        not file
        not path /assets/*
    }
    rewrite @spa_not_found /index.html
"""
    return f"""{addresses} {{
    root * /srv/sites/{primary_host}
    encode zstd gzip

    header {{
        X-Content-Type-Options nosniff
        X-Frame-Options SAMEORIGIN
        Referrer-Policy strict-origin-when-cross-origin
        -Server
    }}

    @static_assets path_regexp \\.({CACHE_EXTENSIONS})$
    header @static_assets Cache-Control "public, max-age=2592000, immutable"
{spa_block}
    file_server
}}
"""


class DeployError(Exception):
    pass


async def _run(cmd: list[str], stdin_text: str | None = None) -> str:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE if stdin_text is not None else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate(stdin_text.encode() if stdin_text else None)
    if proc.returncode != 0:
        raise DeployError(f"{' '.join(cmd[:3])}... 失败: {err.decode()[:500]}")
    return out.decode()


async def pick_node(db: AsyncSession) -> Node:
    from sqlalchemy import select

    node = (
        (await db.execute(select(Node).where(Node.status == "active").order_by(Node.id)))
        .scalars()
        .first()
    )
    if not node:
        raise DeployError("没有可用的边缘节点")
    return node


async def deploy_site(
    db: AsyncSession,
    site: Site,
    staging_path: str,
    spa: bool,
) -> str:
    """把暂存区内容部署为 site.host，返回站点 URL。"""
    settings = get_settings()
    node = await db.get(Node, site.node_id)
    if not node:
        raise DeployError("站点节点不存在")
    host = site.host

    # 1. 持久化到控制面
    target = Path(settings.sites_dir) / host
    target.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(target)
    shutil.copytree(staging_path, target)

    # 2. rsync 到边缘节点
    await _run(
        [
            "rsync",
            "-az",
            "--delete",
            "-e",
            " ".join(["ssh", *SSH_OPTS]),
            f"{target}/",
            f"{node.ssh_user}@{node.ip}:/srv/sites/{host}/",
        ]
    )

    # 3. 安装 Caddy 片段并 reload（节点固定脚本，sudoers 白名单）
    snippet = render_caddy_snippet(host, await _active_domain_hosts(db, site), spa)
    await _install_snippet(node, host, snippet)

    url = f"https://{host}"
    await log.ainfo("site_deployed", host=host, node=node.name)
    return url


async def _active_domain_hosts(db: AsyncSession, site: Site) -> list[str]:
    from sqlalchemy import select

    from ..models import Domain

    rows = (
        (
            await db.execute(
                select(Domain).where(Domain.site_id == site.id, Domain.status == "active")
            )
        )
        .scalars()
        .all()
    )
    return [d.domain for d in rows]


async def _install_snippet(node: Node, host: str, snippet: str) -> None:
    cmd = [
        "ssh",
        *SSH_OPTS,
        f"{node.ssh_user}@{node.ip}",
        "sudo",
        "/usr/local/bin/tt2-caddy-install",
        host,
    ]
    await _run(cmd, stdin_text=snippet)


async def sync_site_domains(db: AsyncSession, site: Site) -> None:
    """域名状态变化后，重新生成该站点的 Caddy 片段。"""
    node = await db.get(Node, site.node_id)
    if not node:
        raise DeployError("站点节点不存在")
    snippet = render_caddy_snippet(site.host, await _active_domain_hosts(db, site), site.spa)
    await _install_snippet(node, site.host, snippet)


async def remove_site_from_node(site: Site, node: Node) -> None:
    try:
        await _run(
            [
                "ssh",
                *SSH_OPTS,
                f"{node.ssh_user}@{node.ip}",
                "sudo",
                "/usr/local/bin/tt2-caddy-remove",
                site.host,
            ]
        )
    except DeployError:
        await log.awarning("caddy_remove_failed", host=site.host)
