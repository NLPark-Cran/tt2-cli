"""猹询码 agent loop：glm-5.3-flash（TokenDance 网关）+ 白名单工具。

借鉴 EVA 的极简受限工具哲学与 kimi-code 的结构清晰度。
运行方式：python -m app.chaxunma.worker
"""

import asyncio
import json
from pathlib import Path

from sqlalchemy import select

from ..config import get_settings
from ..core.logging import get_logger
from ..core.security import decrypt_secret
from ..db import SessionLocal
from ..models import Site, Task, TaskStatus, TokenDanceKey
from ..services.deployer import DeployError, deploy_site, pick_node
from ..services.quota import QuotaExceeded, consume_free_pool
from ..services.tokendance import TokenDanceCallError, chat_completions
from .prompts import SYSTEM_PROMPT
from .tools import TOOL_SCHEMAS, ToolContext, run_local_tool

log = get_logger("chaxunma")

MAX_TOOL_ITERATIONS = 12


class BillingKey:
    """解析本任务应使用的 TokenDance Key：优先用户 TokenPay，耗尽降级共享免费池。"""

    def __init__(self) -> None:
        self.key: str | None = None
        self.billing = "tokenpay"
        self.block_reason: str | None = None


async def _resolve_billing(task: Task, redis) -> BillingKey:  # noqa: ANN001
    result = BillingKey()
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
    if not row:
        result.block_reason = (
            "尚未连接 TokenPay。请访问 https://free.hub.tt2.li/console 完成 TokenDance 授权后重试。"
        )
        return result
    result.key = decrypt_secret(row.key_enc)
    return result


async def _downgrade_to_free_pool(result: BillingKey, redis) -> bool:  # noqa: ANN001
    settings = get_settings()
    if not settings.platform_tokendance_key:
        return False
    try:
        await consume_free_pool(redis)
    except QuotaExceeded as e:
        result.block_reason = e.message
        return False
    result.key = settings.platform_tokendance_key
    result.billing = "free_pool"
    return True


async def run_task(task_id: str, redis) -> None:  # noqa: ANN001
    """执行一个任务（可能被 reply 重新入队多次）。"""
    async with SessionLocal() as db:
        task = await db.get(Task, task_id)
        if not task or task.status not in (TaskStatus.QUEUED.value, TaskStatus.RUNNING.value):
            return
        task.status = TaskStatus.RUNNING.value
        await db.commit()

    try:
        await asyncio.wait_for(
            _run_task_inner(task_id, redis),
            timeout=get_settings().task_timeout_seconds,
        )
    except TimeoutError:
        await _finalize(task_id, status=TaskStatus.FAILED.value, error="任务超时（10 分钟）")
    except Exception as e:  # noqa: BLE001 — worker 不能因单任务崩溃
        await log.aexception("task_crashed", task_id=task_id)
        await _finalize(
            task_id, status=TaskStatus.FAILED.value, error=f"内部错误: {type(e).__name__}"
        )


async def _run_task_inner(task_id: str, redis) -> None:  # noqa: ANN001
    async with SessionLocal() as db:
        task = await db.get(Task, task_id)
        assert task is not None
        messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}, *task.messages]
        staging = Path(task.staging_path)

    billing = await _resolve_billing(task, redis)
    if billing.block_reason:
        await _finalize(task_id, status=TaskStatus.FAILED.value, error=billing.block_reason)
        return

    ctx = ToolContext(staging)
    url: str | None = None

    for _ in range(MAX_TOOL_ITERATIONS):
        assert billing.key is not None
        try:
            resp = await chat_completions(billing.key, messages, tools=TOOL_SCHEMAS)
        except TokenDanceCallError as e:
            can_downgrade = billing.billing == "tokenpay" and e.recovery_action
            if can_downgrade and await _downgrade_to_free_pool(billing, redis):
                await log.ainfo("downgrade_to_free_pool", task_id=task_id, action=e.recovery_action)
                continue
            reason = (
                "TokenPay 额度不足或 Key 已失效，且共享免费池不可用。"
                f"请在控制台重新授权：https://free.hub.tt2.li/console（{e.message}）"
            )
            await _finalize(task_id, status=TaskStatus.FAILED.value, error=reason)
            return

        choice = resp["choices"][0]
        msg = choice["message"]
        messages.append(msg)

        tool_calls = msg.get("tool_calls") or []
        if not tool_calls:
            # 模型没有调工具：把文本反馈记录，提示其必须调用工具收尾
            messages.append(
                {
                    "role": "user",
                    "content": "请使用工具完成部署（deploy/finish/ask_user/fail 之一）。",
                }
            )
            continue

        for call in tool_calls:
            name = call["function"]["name"]
            try:
                args = json.loads(call["function"]["arguments"] or "{}")
            except json.JSONDecodeError:
                args = {}
            result = run_local_tool(ctx, name, args)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": result,
                }
            )

        # 部署请求：由服务端（而非模型）真正执行，工具白名单的唯一出口
        if ctx.deploy_requested:
            ctx.deploy_requested = False
            url_or_error = await _do_deploy(task_id, ctx)
            if isinstance(url_or_error, str) and url_or_error.startswith("https://"):
                url = url_or_error
                messages.append(
                    {
                        "role": "user",
                        "content": f"deploy 工具结果：部署成功，URL={url}。请调用 finish 总结。",
                    }
                )
            else:
                messages.append({"role": "user", "content": f"deploy 工具结果：{url_or_error}"})
            continue

        if ctx.question:
            await _finalize(
                task_id,
                status=TaskStatus.NEEDS_INPUT.value,
                question=ctx.question,
                messages=messages[1:],  # 不持久化 system
                billing=billing.billing,
            )
            return

        if ctx.fail_reason:
            await _finalize(
                task_id,
                status=TaskStatus.FAILED.value,
                error=ctx.fail_reason,
                messages=messages[1:],
                billing=billing.billing,
            )
            return

        if ctx.finish_summary:
            if not url:
                messages.append({"role": "user", "content": "你还没有成功 deploy，不能 finish。"})
                ctx.finish_summary = None
                continue
            await _finalize(
                task_id,
                status=TaskStatus.DONE.value,
                result={"url": url, "summary": ctx.finish_summary},
                messages=messages[1:],
                billing=billing.billing,
            )
            return

    await _finalize(
        task_id,
        status=TaskStatus.FAILED.value,
        error="任务超过最大处理步数",
        messages=messages[1:],
        billing=billing.billing,
    )


async def _do_deploy(task_id: str, ctx: ToolContext) -> str:
    """真正执行部署（服务端可信路径）。返回 URL 或错误描述。"""
    async with SessionLocal() as db:
        task = await db.get(Task, task_id)
        assert task is not None
        spa = bool(ctx.config.get("spa"))

        site = None
        if task.site_id:
            site = await db.get(Site, task.site_id)
        if not site:
            node = await pick_node(db)
            host = f"{task.site_name}.{node.suffix}"
            clash = (
                (await db.execute(select(Site).where(Site.host == host, Site.status == "active")))
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


async def _finalize(task_id: str, **fields) -> None:  # noqa: ANN003
    async with SessionLocal() as db:
        task = await db.get(Task, task_id)
        if not task:
            return
        for key, value in fields.items():
            setattr(task, key, value)
        await db.commit()
    await log.ainfo("task_finalized", task_id=task_id, status=fields.get("status"))
