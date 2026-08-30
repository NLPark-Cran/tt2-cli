"""配额（真实 Redis db 15）。"""

import pytest
import redis.asyncio as aioredis

from app.config import get_settings
from app.services.quota import (
    QuotaExceeded,
    consume_free_pool,
    consume_task_quota,
    rate_limit,
)


@pytest.fixture
async def redis():
    r = aioredis.from_url(get_settings().redis_url, decode_responses=True)
    await r.flushdb()
    yield r
    await r.aclose()


class TestTaskQuota:
    async def test_under_limit(self, redis):
        await consume_task_quota(redis, 1)
        await consume_task_quota(redis, 1)

    async def test_over_limit(self, redis, monkeypatch):
        monkeypatch.setattr(get_settings(), "max_tasks_per_day", 2)
        await consume_task_quota(redis, 2)
        await consume_task_quota(redis, 2)
        with pytest.raises(QuotaExceeded):
            await consume_task_quota(redis, 2)


class TestFreePool:
    async def test_pool(self, redis, monkeypatch):
        monkeypatch.setattr(get_settings(), "free_pool_daily", 1)
        await consume_free_pool(redis)
        with pytest.raises(QuotaExceeded) as exc:
            await consume_free_pool(redis)
        assert "TokenPay" in exc.value.message


class TestRateLimit:
    async def test_rate_limit(self, redis):
        for _ in range(3):
            await rate_limit(redis, "test-scope", 3, 60)
        with pytest.raises(QuotaExceeded):
            await rate_limit(redis, "test-scope", 3, 60)
