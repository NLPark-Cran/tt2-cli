"""猹询码接入层：计费解析、免费池降级、部署桥接、结果持久化。

agent loop 本体在 cran-code@lite 的 chaxunma 包；本模块只做胶水。
"""

import asyncio
from pathlib import Path

from chaxunma import AgentLoop, ModelCallError, ToolContext
from sqlalchemy import select

from ..config import get_settings
from ..core.logging import get_logger
from ..core.security import decrypt_secret
from ..db import SessionLocal
from ..models import Site, Task, TaskStatus, TokenDanceKey
from ..services.deployer import DeployError, deploy_site, pick_node
from ..services.quota import QuotaExceeded, consume_free_pool

log = get_logger("chaxunma")


async def _resolve_user_key(task: Task) -> str | None:
    """取用户 TokenPay 授权的 TokenDance Key。无授权返回 None。"""
    async with SessionLocal() as db:
        row = (
            (
                await db.execute(
                    select(TokenDanceKey).where(
                        TokenDanceKey.user_id == task.user_id, TokenDanceKey.active.is_(True)
                    )
                )
            )
            .scalars()
            .first()
        )
    return decrypt_secret(row.key_enc) if row else None


async def _try_free_pool(redis) -> str | None:  # noqa: ANN001
    """降级到共享免费池（平台 Key）。池空或无平台 Key 返回 None。"""
    settings = get_settings()
    if not settings.platform_tokendance_key:
        return None
    try:
        await consume_free_pool(redis)
    except QuotaExceeded:
        return None
    return settings.platform_tokendance_key


def _make_deploy(task_id: str):
    """deploy 回调：猹询码副作用的唯一出口，由服务端可信路径执行。"""

    async def deploy(ctx: ToolContext) -> str:
        spa = bool(ctx.config.get("spa"))
        async with SessionLocal() as db:
            task = await db.get(Task, task_id)
            if not task:
                return "错误：任务不存在"
            site = await db.get(Site, task.site_id) if task.site_id else None
            if not site:
                node = await pick_node(db)
                host = f"{task.site_name}.{node.suffix}"
                clash = (
                    (
                        await db.execute(
                            select(Site).where(Site.host == host, Site.status == "active")
                        )
                    )
                    .scalars()
                    .first()
                )
                if clash:
                    return (
                        f"错误：站点名 {task.site_name} 已被占用（name_taken）。"
                        "请用 ask_user 询问用户换新名字。"
                    )
                site = Site(
                    user_id=task.user_id,
                    node_id=node.id,
                    name=task.site_name,
                    host=host,
                    spa=spa,
                )
                db.add(site)
                await db.flush()
                task.site_id = site.id
            else:
                site.spa = spa
            try:
                url = await deploy_site(db, site, task.staging_path, spa)
            except DeployError as e:
                return f"错误：部署失败：{e}"
            await db.commit()
            return url

    return deploy


async def run_task(task_id: str, redis) -> None:  # noqa: ANN001
    """执行一个任务（reply 会重新入队）。永不向上抛异常。"""
    async with SessionLocal() as db:
        task = await db.get(Task, task_id)
        if not task or task.status not in (TaskStatus.QUEUED.value, TaskStatus.RUNNING.value):
            return
        task.status = TaskStatus.RUNNING.value
        history: list[dict] = list(task.messages)
        staging_path = task.staging_path
        await db.commit()

    try:
        await asyncio.wait_for(
            _run_inner(task_id, history, staging_path, redis),
            timeout=get_settings().task_timeout_seconds,
        )
    except TimeoutError:
        await _finalize(task_id, status=TaskStatus.FAILED.value, error="任务超时（10 分钟）")
    except Exception as e:  # noqa: BLE001 — worker 不能因单任务崩溃
        await log.aexception("task_crashed", task_id=task_id)
        await _finalize(
            task_id, status=TaskStatus.FAILED.value, error=f"内部错误: {type(e).__name__}"
        )


async def _run_inner(task_id: str, history: list[dict], staging_path: str, redis) -> None:  # noqa: ANN001
    settings = get_settings()
    async with SessionLocal() as db:
        task = await db.get(Task, task_id)
        assert task is not None

    api_key = await _resolve_user_key(task)
    billing = "tokenpay"
    if not api_key:
        await _finalize(
            task_id,
            status=TaskStatus.FAILED.value,
            error=(
                "尚未连接 TokenPay。请访问 https://free.hub.tt2.li/console "
                "完成 TokenDance 授权后重试。"
            ),
        )
        return

    ctx = ToolContext(Path(staging_path))
    deploy = _make_deploy(task_id)

    async def _run_loop(key: str):
        loop = AgentLoop(
            api_key=key,
            model=settings.chaxunma_model,
            base_url=settings.tokendance_base_url,
            app_url=settings.app_url,
        )
        return await loop.run(history, ctx, deploy)

    try:
        outcome = await _run_loop(api_key)
    except ModelCallError as e:
        # TokenPay 额度/Key 问题 → 尝试降级到共享免费池后重试一次
        platform_key = None
        if e.recovery_action:
            platform_key = await _try_free_pool(redis)
        if not platform_key:
            reason = (
                "TokenPay 额度不足或 Key 已失效，且共享免费池不可用。"
                f"请在控制台重新授权：https://free.hub.tt2.li/console（{e}）"
            )
            await _finalize(task_id, status=TaskStatus.FAILED.value, error=reason)
            return
        await log.ainfo("downgrade_to_free_pool", task_id=task_id, action=e.recovery_action)
        billing = "free_pool"
        # 修补工具是幂等失败的（old 找不到会报错但不崩溃），重跑安全
        ctx = ToolContext(Path(staging_path))
        try:
            outcome = await _run_loop(platform_key)
        except ModelCallError as e2:
            await _finalize(task_id, status=TaskStatus.FAILED.value, error=f"模型服务不可用：{e2}")
            return

    await _finalize(
        task_id,
        status={
            "done": TaskStatus.DONE.value,
            "needs_input": TaskStatus.NEEDS_INPUT.value,
            "failed": TaskStatus.FAILED.value,
            "over_steps": TaskStatus.FAILED.value,
        }[outcome.kind],
        question=outcome.question,
        result=outcome.result,
        error=outcome.error,
        messages=outcome.messages or None,
        billing=billing,
    )


async def _finalize(task_id: str, **fields) -> None:  # noqa: ANN003
    fields = {k: v for k, v in fields.items() if v is not None}
    async with SessionLocal() as db:
        task = await db.get(Task, task_id)
        if not task:
            return
        for key, value in fields.items():
            setattr(task, key, value)
        await db.commit()
    await log.ainfo("task_finalized", task_id=task_id, status=fields.get("status"))
