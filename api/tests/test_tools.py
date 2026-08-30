"""猹询码白名单工具。"""

from pathlib import Path

from app.chaxunma.tools import ToolContext, run_local_tool


def _ctx(tmp_path: Path) -> ToolContext:
    (tmp_path / "index.html").write_text('<html><script src="./app.js"></script></html>')
    (tmp_path / "app.js").write_text("console.log('hi')")
    return ToolContext(tmp_path)


class TestListRead:
    def test_list(self, tmp_path):
        out = run_local_tool(_ctx(tmp_path), "list_files", {})
        assert "index.html" in out and "app.js" in out

    def test_read(self, tmp_path):
        out = run_local_tool(_ctx(tmp_path), "read_file", {"path": "index.html"})
        assert "app.js" in out

    def test_read_missing(self, tmp_path):
        out = run_local_tool(_ctx(tmp_path), "read_file", {"path": "nope.html"})
        assert "错误" in out


class TestPathEscape:
    def test_read_escape(self, tmp_path):
        out = run_local_tool(_ctx(tmp_path), "read_file", {"path": "../../etc/passwd"})
        assert "错误" in out

    def test_patch_escape(self, tmp_path):
        out = run_local_tool(
            _ctx(tmp_path), "patch_text", {"path": "/etc/hostname", "old": "a", "new": "b"}
        )
        assert "错误" in out


class TestPatch:
    def test_patch_ok(self, tmp_path):
        ctx = _ctx(tmp_path)
        out = run_local_tool(
            ctx, "patch_text", {"path": "index.html", "old": "./app.js", "new": "app.js"}
        )
        assert "已修补" in out
        assert "app.js" in (tmp_path / "index.html").read_text()

    def test_patch_not_unique(self, tmp_path):
        (tmp_path / "index.html").write_text("aaa aaa")
        out = run_local_tool(
            _ctx(tmp_path), "patch_text", {"path": "index.html", "old": "aaa", "new": "b"}
        )
        assert "唯一" in out

    def test_write_file(self, tmp_path):
        ctx = _ctx(tmp_path)
        out = run_local_tool(ctx, "write_file", {"path": "404.html", "content": "not found"})
        assert "已写入" in out
        assert (tmp_path / "404.html").exists()


class TestFlowTools:
    def test_config_deploy_ask_finish_fail(self, tmp_path):
        ctx = _ctx(tmp_path)
        run_local_tool(ctx, "decide_config", {"spa": True})
        assert ctx.config["spa"] is True
        run_local_tool(ctx, "deploy", {})
        assert ctx.deploy_requested
        run_local_tool(ctx, "ask_user", {"question": "SPA?", "options": ["是", "否"]})
        assert ctx.question and ctx.question["options"] == ["是", "否"]
        run_local_tool(ctx, "finish", {"summary": "done"})
        assert ctx.finish_summary == "done"
        ctx2 = _ctx(tmp_path)
        run_local_tool(ctx2, "fail", {"reason": "违规内容"})
        assert ctx2.fail_reason

    def test_unknown_tool(self, tmp_path):
        out = run_local_tool(_ctx(tmp_path), "exec_shell", {})
        assert "未知工具" in out
