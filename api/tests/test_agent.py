"""猹询码接入层端到端（AgentLoop._chat 脚本化 + deploy_site 打桩）。"""

import json
from pathlib import Path

import pytest
import redis.asyncio as aioredis
from chaxunma import AgentLoop

from app.chaxunma import agent
from app.config import get_settings
from app.core.security import encrypt_secret, new_task_id
from app.models import Node, Site, Task, TokenDanceKey, User


@pytest.fixture
async def redis():
    r = aioredis.from_url(get_settings().redis_url, decode_responses=True)
    await r.flushdb()
    yield r
    await r.aclose()


def _tool_call(call_id: str, name: str, args: dict) -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args)},
    }


def _assistant_msg(*tool_calls: dict) -> dict:
    message = {"role": "assistant", "content": None, "tool_calls": list(tool_calls)}
    return {"choices": [{"message": message}]}


async def _make_task(db_session, user, name="demo") -> Task:
    staging = Path(get_settings().staging_dir) / new_task_id()
    staging.mkdir(parents=True, exist_ok=True)
    (staging / "index.html").write_text("<html>hello</html>")
    task = Task(
        id=new_task_id(),
        user_id=user.id,
        site_name=name,
        staging_path=str(staging),
        messages=[{"role": "user", "content": "deploy"}],
    )
    db_session.add(task)
    await db_session.commit()
    return task


@pytest.fixture
async def user(db_session):
    user = User(watcha_user_id=8888, nickname="agent测试")
    db_session.add(user)
    db_session.add(Node(name="n1", ip="127.0.0.1", suffix="lhub.tt2.li", ssh_user="deploy"))
    await db_session.commit()
    return user


@pytest.fixture
async def paid_user(db_session, user):
    db_session.add(TokenDanceKey(user_id=user.id, key_enc=encrypt_secret("sk-x")))
    await db_session.commit()
    return user


def _patch_chat(monkeypatch, script: list[dict]):
    calls = {"n": 0}

    async def fake_chat(self, messages):
        resp = script[min(calls["n"], len(script) - 1)]
        calls["n"] += 1
        return resp

    monkeypatch.setattr(AgentLoop, "_chat", fake_chat)
    return calls


def _patch_deploy(monkeypatch):
    async def fake_deploy(db, site, staging, spa):
        return f"https://{site.host}"

    monkeypatch.setattr(agent, "deploy_site", fake_deploy)


class TestBillingBlock:
    async def test_no_tokendance_key_fails_with_guidance(self, db_session, user, redis):
        task = await _make_task(db_session, user)
        await agent.run_task(task.id, redis)
        await db_session.refresh(task)
        assert task.status == "failed"
        assert "TokenPay" in (task.error or "")


class TestHappyPath:
    async def test_deploy_flow(self, db_session, paid_user, redis, monkeypatch):
        task = await _make_task(db_session, paid_user)
        _patch_chat(
            monkeypatch,
            [
                _assistant_msg(_tool_call("c1", "list_files", {})),
                _assistant_msg(_tool_call("c2", "decide_config", {"spa": False})),
                _assistant_msg(_tool_call("c3", "deploy", {})),
                _assistant_msg(_tool_call("c4", "finish", {"summary": "上线完成"})),
            ],
        )
        _patch_deploy(monkeypatch)

        await agent.run_task(task.id, redis)
        await db_session.refresh(task)
        assert task.status == "done", task.error
        assert task.result["url"] == "https://demo.lhub.tt2.li"
        assert task.billing == "tokenpay"

        from sqlalchemy import select

        site = (await db_session.execute(select(Site).where(Site.name == "demo"))).scalars().first()
        assert site is not None and site.host == "demo.lhub.tt2.li"


class TestAskUser:
    async def test_needs_input(self, db_session, paid_user, redis, monkeypatch):
        task = await _make_task(db_session, paid_user)
        _patch_chat(
            monkeypatch,
            [
                _assistant_msg(
                    _tool_call(
                        "c1",
                        "ask_user",
                        {
                            "question": "这是 SPA 吗？",
                            "options": ["是", "否"],
                        },
                    )
                ),
            ],
        )
        await agent.run_task(task.id, redis)
        await db_session.refresh(task)
        assert task.status == "needs_input"
        assert task.question["options"] == ["是", "否"]


class TestFreePoolDowngrade:
    async def test_downgrade_on_quota(self, db_session, paid_user, redis, monkeypatch):
        task = await _make_task(db_session, paid_user)
        monkeypatch.setattr(get_settings(), "platform_tokendance_key", "sk-platform")

        from chaxunma import ModelCallError

        calls = {"n": 0}

        async def fake_chat(self, messages):
            if calls["n"] == 0:
                calls["n"] += 1
                raise ModelCallError("quota", recovery_action="api_key_quota")
            return _assistant_msg(_tool_call("c1", "fail", {"reason": "测试终止"}))

        monkeypatch.setattr(AgentLoop, "_chat", fake_chat)
        await agent.run_task(task.id, redis)
        await db_session.refresh(task)
        assert task.billing == "free_pool"
        assert task.status == "failed"  # fail 工具终止


class TestFreePoolExhausted:
    async def test_no_platform_key_fails(self, db_session, paid_user, redis, monkeypatch):
        task = await _make_task(db_session, paid_user)
        monkeypatch.setattr(get_settings(), "platform_tokendance_key", "")

        from chaxunma import ModelCallError

        async def fake_chat(self, messages):
            raise ModelCallError("quota", recovery_action="api_key_quota")

        monkeypatch.setattr(AgentLoop, "_chat", fake_chat)
        await agent.run_task(task.id, redis)
        await db_session.refresh(task)
        assert task.status == "failed"
        assert "重新授权" in (task.error or "")
