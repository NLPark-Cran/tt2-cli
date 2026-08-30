"""测试环境：使用 tt2_test 数据库与 redis db 15。"""

import os

os.environ.setdefault("TT2_DATABASE_URL", "postgresql+asyncpg://tt2:tt2@127.0.0.1:5432/tt2_test")
os.environ.setdefault("TT2_REDIS_URL", "redis://127.0.0.1:6379/15")
os.environ.setdefault("TT2_FERNET_KEY", "LLsgdHqlFBOukbTG5_OhVV_upvzOD2pAy0-f3rKYkoM=")
os.environ.setdefault("TT2_SESSION_SECRET", "test-secret")
os.environ.setdefault("TT2_STAGING_DIR", "/tmp/tt2_test_staging")  # noqa: S108
os.environ.setdefault("TT2_SITES_DIR", "/tmp/tt2_test_sites")  # noqa: S108

import pytest_asyncio  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402


@pytest_asyncio.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


@pytest_asyncio.fixture
async def db_session():
    """每个测试独立引擎+会话（避免跨事件循环），并覆盖应用依赖。"""
    import redis.asyncio as aioredis

    from app.config import get_settings
    from app.db import get_db
    from app.deps import get_redis
    from app.main import app
    from app.models import Base

    engine = create_async_engine(get_settings().database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    redis = aioredis.from_url(get_settings().redis_url, decode_responses=True)

    # 猹询码 worker/agent 直接使用 SessionLocal，测试时替换为测试工厂
    import app.chaxunma.agent as agent_mod

    original_session_local = agent_mod.SessionLocal
    agent_mod.SessionLocal = session_factory

    async def override_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_redis] = lambda: redis

    async with session_factory() as session:
        yield session

    app.dependency_overrides.clear()
    agent_mod.SessionLocal = original_session_local
    await redis.aclose()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
