"""配额与限流（Redis）。所有计数键都带 TTL，服务重启不影响正确性。"""

from datetime import UTC, datetime

from redis.asyncio import Redis

from ..config import get_settings


def _today() -> str:
    return datetime.now(UTC).strftime("%Y%m%d")


class QuotaExceeded(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message


async def consume_task_quota(redis: Redis, user_id: int) -> None:
    """每用户每日任务限额。"""
    settings = get_settings()
    key = f"quota:tasks:{_today()}:{user_id}"
    used = await redis.incr(key)
    if used == 1:
        await redis.expire(key, 90000)  # 25h
    if used > settings.max_tasks_per_day:
        raise QuotaExceeded(
            "daily_task_limit", f"已达每日任务上限（{settings.max_tasks_per_day} 次）"
        )


async def consume_free_pool(redis: Redis) -> None:
    """全平台共享免费任务池：先到先得，超限抛错。"""
    settings = get_settings()
    key = f"quota:freepool:{_today()}"
    used = await redis.incr(key)
    if used == 1:
        await redis.expire(key, 90000)
    if used > settings.free_pool_daily:
        raise QuotaExceeded(
            "free_pool_exhausted",
            "今日共享免费任务额度已用完。授权 TokenPay 可获得稳定的专属额度：https://free.hub.tt2.li/console",
        )


async def rate_limit(redis: Redis, scope: str, limit: int, window_seconds: int) -> None:
    """简单滑动窗口限速（INCR + EXPIRE 近似）。"""
    key = f"rl:{scope}"
    used = await redis.incr(key)
    if used == 1:
        await redis.expire(key, window_seconds)
    if used > limit:
        raise QuotaExceeded("rate_limited", "请求过于频繁，请稍后再试")
