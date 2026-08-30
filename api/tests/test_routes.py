"""设备码流、Token 管理、站点与域名路由。"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.security import new_cli_token
from app.main import app
from app.models import CliToken, Node, Site, User


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
async def user_token(db_session):
    user = User(watcha_user_id=7777, nickname="路由测试")
    db_session.add(user)
    db_session.add(Node(name="n1", ip="127.0.0.1", suffix="lhub.tt2.li", ssh_user="deploy"))
    await db_session.flush()
    plain, hashed, _ = new_cli_token()
    db_session.add(CliToken(user_id=user.id, name="t", prefix=plain[:16], token_hash=hashed))
    await db_session.commit()
    return user, plain


def _auth(plain: str) -> dict:
    return {"Authorization": f"Bearer {plain}"}


class TestDeviceFlow:
    async def test_full_flow(self, client, user_token):
        _, plain = user_token
        resp = await client.post("/api/v1/auth/device")
        assert resp.status_code == 200
        data = resp.json()
        assert "device_code" in data and "user_code" in data

        # 未批准时轮询 pending
        resp = await client.get(
            "/api/v1/auth/device/poll", params={"device_code": data["device_code"]}
        )
        assert resp.json()["status"] == "pending"

        # 用户批准
        resp = await client.post(
            "/api/v1/auth/device/approve",
            params={"user_code": data["user_code"]},
            headers=_auth(plain),
        )
        assert resp.status_code == 200

        # 轮询拿到 token（一次性）
        resp = await client.get(
            "/api/v1/auth/device/poll", params={"device_code": data["device_code"]}
        )
        body = resp.json()
        assert body["status"] == "approved"
        assert body["token"].startswith("tt2_pat_")

        # 新 token 可用
        resp = await client.get("/api/v1/auth/me", headers=_auth(body["token"]))
        assert resp.status_code == 200

        # 二次领取失败
        resp = await client.get(
            "/api/v1/auth/device/poll", params={"device_code": data["device_code"]}
        )
        assert resp.status_code == 410

    async def test_approve_requires_auth(self, client):
        resp = await client.post("/api/v1/auth/device/approve", params={"user_code": "ABCD-EFGH"})
        assert resp.status_code == 401

    async def test_approve_unknown_code(self, client, user_token):
        _, plain = user_token
        resp = await client.post(
            "/api/v1/auth/device/approve", params={"user_code": "ZZZZ-YYYY"}, headers=_auth(plain)
        )
        assert resp.status_code == 404


class TestTokens:
    async def test_create_list_revoke(self, client, user_token):
        _, plain = user_token
        resp = await client.post("/api/v1/tokens", params={"name": "cli"}, headers=_auth(plain))
        assert resp.status_code == 200
        new_plain = resp.json()["token"]
        prefix = resp.json()["prefix"]

        resp = await client.get("/api/v1/tokens", headers=_auth(plain))
        names = [t["name"] for t in resp.json()]
        assert "cli" in names and "t" in names

        resp = await client.delete(f"/api/v1/tokens/{prefix}", headers=_auth(plain))
        assert resp.status_code == 200
        # 吊销后失效
        resp = await client.get("/api/v1/auth/me", headers=_auth(new_plain))
        assert resp.status_code == 401


class TestSites:
    async def test_list_empty(self, client, user_token):
        _, plain = user_token
        resp = await client.get("/api/v1/sites", headers=_auth(plain))
        assert resp.json() == []

    async def test_delete(self, client, user_token, db_session, monkeypatch):
        user, plain = user_token
        db_session.add(Site(user_id=user.id, node_id=1, name="s1", host="s1.lhub.tt2.li"))
        await db_session.commit()

        async def fake_remove(site, node):
            return None

        monkeypatch.setattr("app.routers.sites.remove_site_from_node", fake_remove)
        resp = await client.delete("/api/v1/sites/s1", headers=_auth(plain))
        assert resp.status_code == 200
        resp = await client.get("/api/v1/sites", headers=_auth(plain))
        assert resp.json() == []


class TestDomains:
    async def test_add_list_delete(self, client, user_token, db_session):
        user, plain = user_token
        db_session.add(Site(user_id=user.id, node_id=1, name="site2", host="site2.lhub.tt2.li"))
        await db_session.commit()

        resp = await client.post(
            "/api/v1/domains",
            json={"site": "site2", "domain": "WWW.88sj.com"},
            headers=_auth(plain),
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["domain"] == "www.88sj.com"
        assert body["dns_guide"]["recommended"]["value"] == "site2.lhub.tt2.li"

        # 重复绑定
        resp = await client.post(
            "/api/v1/domains",
            json={"site": "site2", "domain": "www.88sj.com"},
            headers=_auth(plain),
        )
        assert resp.status_code == 409

        resp = await client.get("/api/v1/domains", headers=_auth(plain))
        assert len(resp.json()) == 1

        resp = await client.get("/api/v1/domains/www.88sj.com/check", headers=_auth(plain))
        assert resp.status_code == 200
        assert resp.json()["dns_ok"] is False  # 测试域名解析不到节点

        resp = await client.delete("/api/v1/domains/www.88sj.com", headers=_auth(plain))
        assert resp.status_code == 200

    async def test_add_unknown_site(self, client, user_token):
        _, plain = user_token
        resp = await client.post(
            "/api/v1/domains", json={"site": "ghost", "domain": "a.b.com"}, headers=_auth(plain)
        )
        assert resp.status_code == 404


class TestMisc:
    async def test_validation_error_format(self, client, user_token):
        _, plain = user_token
        resp = await client.post("/api/v1/domains", json={"site": "x"}, headers=_auth(plain))
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "validation_error"

    async def test_list_tasks(self, client, user_token):
        _, plain = user_token
        resp = await client.get("/api/v1/tasks", headers=_auth(plain))
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_unknown_task(self, client, user_token):
        _, plain = user_token
        resp = await client.get("/api/v1/tasks/t_nonexistent", headers=_auth(plain))
        assert resp.status_code == 404


class TestTokenDanceConnect:
    async def test_connect_url(self, client, user_token):
        _, plain = user_token
        resp = await client.get("/api/v1/auth/tokendance/connect", headers=_auth(plain))
        assert resp.status_code == 200
        url = resp.json()["authorize_url"]
        assert "code_challenge" in url and "app_url=" in url
