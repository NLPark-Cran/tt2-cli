"""任务：push / reply / 查询。全部部署流量都经过这里进入猹询码。"""

import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..core.errors import err
from ..core.security import new_task_id
from ..core.validators import safe_extract_tar, validate_site_name
from ..db import get_db
from ..deps import get_current_user, get_redis
from ..models import Site, Task, TaskStatus, User
from ..schemas import ReplyIn, TaskCreated, TaskOut
from ..services.quota import QuotaExceeded, consume_task_quota, rate_limit

router = APIRouter(prefix="/tasks", tags=["tasks"])

QUEUE_KEY = "tt2:task_queue"


def _task_out(t: Task) -> TaskOut:
    return TaskOut(
        task_id=t.id,
        status=t.status,
        kind=t.kind,
        site_name=t.site_name,
        question=t.question,
        result=t.result,
        error=t.error,
        billing=t.billing,
        rounds=t.rounds,
        created_at=t.created_at,
        updated_at=t.updated_at,
    )


@router.post("", response_model=TaskCreated, status_code=201)
async def create_task(
    archive: UploadFile,
    name: str = Form(min_length=3, max_length=32),
    task: str = Form(default="deploy my site", max_length=2000),
    kind: str = Form(default="push"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> TaskCreated:
    settings = get_settings()
    try:
        await rate_limit(redis, f"tasks:{user.id}", 30, 60)
        await consume_task_quota(redis, user.id)
    except QuotaExceeded as e:
        raise err(429, e.code, e.message) from e

    name = validate_site_name(name.lower())

    # 站点名额：新站点才占用名额
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
        count_query = select(Site).where(Site.user_id == user.id, Site.status == "active")
        count = (await db.execute(count_query)).scalars().all()
        if len(count) >= settings.max_sites_per_user:
            raise HTTPException(
                429,
                detail={
                    "error": {
                        "code": "site_limit",
                        "message": f"站点数量已达上限（{settings.max_sites_per_user} 个）",
                        "details": {},
                    }
                },
            )

    # 保存并校验上传包
    task_id = new_task_id()
    staging = Path(settings.staging_dir) / task_id
    staging.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
            size = 0
            while chunk := await archive.read(1024 * 1024):
                size += len(chunk)
                if size > settings.max_upload_bytes:
                    raise err(413, "upload_too_large", "上传包超过 50MB 限制")
                tmp.write(chunk)
            tmp_path = Path(tmp.name)  # noqa: ASYNC240
        safe_extract_tar(tmp_path, staging, settings.max_extracted_bytes)
        tmp_path.unlink(missing_ok=True)  # noqa: ASYNC240
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    if not (staging / "index.html").exists():
        shutil.rmtree(staging, ignore_errors=True)
        raise err(422, "no_index", "包内必须包含 index.html（请先构建为静态产物）")

    row = Task(
        id=task_id,
        user_id=user.id,
        site_id=site.id if site else None,
        kind=kind,
        input_text=task,
        site_name=name,
        staging_path=str(staging),
        messages=[{"role": "user", "content": task}],
    )
    db.add(row)
    await db.commit()
    await redis.rpush(QUEUE_KEY, task_id)
    return TaskCreated(task_id=task_id, status=TaskStatus.QUEUED.value)


@router.get("/{task_id}", response_model=TaskOut)
async def get_task(
    task_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TaskOut:
    t = await db.get(Task, task_id)
    if not t or t.user_id != user.id:
        raise err(404, "task_not_found", "任务不存在")
    return _task_out(t)


@router.get("", response_model=list[TaskOut])
async def list_tasks(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = 20,
) -> list[TaskOut]:
    query = (
        select(Task)
        .where(Task.user_id == user.id)
        .order_by(Task.created_at.desc())
        .limit(min(limit, 100))
    )
    rows = (await db.execute(query)).scalars().all()
    return [_task_out(t) for t in rows]


@router.post("/{task_id}/reply", response_model=TaskOut)
async def reply_task(
    task_id: str,
    body: ReplyIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> TaskOut:
    t = await db.get(Task, task_id)
    if not t or t.user_id != user.id:
        raise err(404, "task_not_found", "任务不存在")
    if t.status != TaskStatus.NEEDS_INPUT.value:
        raise err(409, "not_waiting", "任务当前不在等待输入状态")
    if t.rounds >= get_settings().session_max_rounds:
        raise err(429, "rounds_limit", "本会话轮次已达上限，请提交新任务")

    t.messages = [*t.messages, {"role": "user", "content": body.message}]
    t.question = None
    t.status = TaskStatus.QUEUED.value
    t.rounds += 1
    await db.commit()
    await redis.rpush(QUEUE_KEY, task_id)
    return _task_out(t)
