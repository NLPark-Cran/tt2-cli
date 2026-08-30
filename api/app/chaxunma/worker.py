"""猹询码 worker：从 Redis 队列领取任务并执行。

独立进程运行：python -m app.chaxunma.worker
并发由启动进程数控制（默认 2 个 systemd 实例 or WORKER_CONCURRENCY）。
"""

import asyncio
import contextlib

import redis.asyncio as aioredis

from ..config import get_settings
from ..core.logging import get_logger, setup_logging
from .agent import run_task

log = get_logger("chaxunma-worker")

QUEUE_KEY = "tt2:task_queue"
CONCURRENCY = 2


async def worker_loop(worker_id: int) -> None:
    redis = aioredis.from_url(get_settings().redis_url, decode_responses=True)
    await log.ainfo("worker_started", worker_id=worker_id)
    while True:
        try:
            item = await redis.blpop(QUEUE_KEY, timeout=30)
            if not item:
                continue
            _, task_id = item
            await run_task(task_id, redis)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — worker 主循环不崩溃
            await log.aexception("worker_loop_error", worker_id=worker_id)
            await asyncio.sleep(2)


async def main() -> None:
    setup_logging()
    tasks = [asyncio.create_task(worker_loop(i)) for i in range(CONCURRENCY)]
    try:
        await asyncio.gather(*tasks)
    finally:
        for t in tasks:
            t.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await t


if __name__ == "__main__":
    asyncio.run(main())
