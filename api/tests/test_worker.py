"""worker 队列消费。"""

import asyncio

import pytest
import redis.asyncio as aioredis

from app.chaxunma import worker
from app.config import get_settings


@pytest.fixture
async def redis():
    r = aioredis.from_url(get_settings().redis_url, decode_responses=True)
    await r.flushdb()
    yield r
    await r.aclose()


class TestWorkerLoop:
    async def test_consumes_queue(self, redis, monkeypatch):
        seen: list[str] = []

        async def fake_run_task(task_id, redis_):
            seen.append(task_id)

        monkeypatch.setattr(worker, "run_task", fake_run_task)

        loop_task = asyncio.create_task(worker.worker_loop(0))
        await redis.rpush(worker.QUEUE_KEY, "t_test_123")
        for _ in range(50):
            if seen:
                break
            await asyncio.sleep(0.1)
        loop_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await loop_task
        assert seen == ["t_test_123"]

    async def test_survives_task_error(self, redis, monkeypatch):
        calls = {"n": 0}

        async def flaky(task_id, redis_):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("boom")

        monkeypatch.setattr(worker, "run_task", flaky)
        loop_task = asyncio.create_task(worker.worker_loop(1))
        await redis.rpush(worker.QUEUE_KEY, "t_bad")
        await redis.rpush(worker.QUEUE_KEY, "t_good")
        for _ in range(50):
            if calls["n"] >= 2:
                break
            await asyncio.sleep(0.1)
        loop_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await loop_task
        assert calls["n"] == 2  # 第一个任务崩了不影响第二个
