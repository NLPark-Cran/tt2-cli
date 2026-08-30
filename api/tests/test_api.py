"""API 端点（httpx ASGI + 真实测试库）。"""

import io
import tarfile

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.security import hash_token, new_cli_token
from app.main import app
from app.models import CliToken, Node, User


def _tar_gz(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, data in entries.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
async def user_token(db_session):
    user = User(watcha_user_id=999999, nickname="测试猹")
    db_session.add(user)
    node = Node(name="test-node", ip="127.0.0.1", suffix="lhub.tt2.li", ssh_user="deploy")
    db_session.add(node)
    await db_session.flush()
    plain, hashed, _ = new_cli_token()
    db_session.add(CliToken(user_id=user.id, name="t", prefix=plain[:16], token_hash=hashed))
    await db_session.commit()
    return user, plain


class TestHealth:
    async def test_health(self, client):
        resp = await client.get("/api/v1/health")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True


class TestAuth:
    async def test_unauthorized(self, client):
        resp = await client.get("/api/v1/sites")
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "unauthorized"

    async def test_me_with_token(self, client, user_token):
        _, plain = user_token
        resp = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {plain}"})
        assert resp.status_code == 200
        assert resp.json()["nickname"] == "测试猹"

    async def test_bad_token(self, client, db_session):
        resp = await client.get("/api/v1/auth/me", headers={"Authorization": "Bearer garbage"})
        assert resp.status_code == 401


class TestTaskCreate:
    async def test_push_ok(self, client, user_token, redis_clean):
        _, plain = user_token
        payload = _tar_gz({"index.html": b"<html>hi</html>"})
        resp = await client.post(
            "/api/v1/tasks",
            headers={"Authorization": f"Bearer {plain}"},
            files={"archive": ("site.tar.gz", payload, "application/gzip")},
            data={"name": "demo1", "task": "deploy"},
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["status"] == "queued"

    async def test_no_index(self, client, user_token, redis_clean):
        _, plain = user_token
        payload = _tar_gz({"readme.txt": b"hi"})
        resp = await client.post(
            "/api/v1/tasks",
            headers={"Authorization": f"Bearer {plain}"},
            files={"archive": ("site.tar.gz", payload, "application/gzip")},
            data={"name": "demo2", "task": "deploy"},
        )
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "no_index"

    async def test_reserved_name(self, client, user_token, redis_clean):
        _, plain = user_token
        payload = _tar_gz({"index.html": b"x"})
        resp = await client.post(
            "/api/v1/tasks",
            headers={"Authorization": f"Bearer {plain}"},
            files={"archive": ("site.tar.gz", payload, "application/gzip")},
            data={"name": "www", "task": "deploy"},
        )
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "reserved_name"

    async def test_malicious_package(self, client, user_token, redis_clean):
        _, plain = user_token
        payload = _tar_gz({"index.html": b"x", "evil.php": b"<?php"})
        resp = await client.post(
            "/api/v1/tasks",
            headers={"Authorization": f"Bearer {plain}"},
            files={"archive": ("site.tar.gz", payload, "application/gzip")},
            data={"name": "demo3", "task": "deploy"},
        )
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "forbidden_extension"


class TestTaskFlow:
    async def test_get_and_reply_wrong_state(self, client, user_token, redis_clean):
        user, plain = user_token
        payload = _tar_gz({"index.html": b"x"})
        resp = await client.post(
            "/api/v1/tasks",
            headers={"Authorization": f"Bearer {plain}"},
            files={"archive": ("site.tar.gz", payload, "application/gzip")},
            data={"name": "demo4", "task": "deploy"},
        )
        task_id = resp.json()["task_id"]

        resp = await client.get(
            f"/api/v1/tasks/{task_id}", headers={"Authorization": f"Bearer {plain}"}
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "queued"

        # 非 needs_input 状态不能 reply
        resp = await client.post(
            f"/api/v1/tasks/{task_id}/reply",
            headers={"Authorization": f"Bearer {plain}"},
            json={"message": "hi"},
        )
        assert resp.status_code == 409

        # 他人不可见
        other_plain = hash_token("x")  # 不存在的 token
        resp = await client.get(
            f"/api/v1/tasks/{task_id}", headers={"Authorization": f"Bearer {other_plain}"}
        )
        assert resp.status_code == 401


@pytest.fixture
async def redis_clean():
    import redis.asyncio as aioredis

    from app.config import get_settings

    r = aioredis.from_url(get_settings().redis_url, decode_responses=True)
    await r.flushdb()
    yield r
    await r.aclose()
