"""猹询码白名单工具集。借鉴 EVA 的受限工具哲学：工具即权限边界。"""

from pathlib import Path
from typing import Any

from fastapi import HTTPException

MAX_READ_CHARS = 20000
MAX_PATCHES_PER_TASK = 50


class ToolContext:
    """一次任务的工具执行上下文。"""

    def __init__(self, staging: Path) -> None:
        self.staging = staging.resolve()
        self.patches = 0
        self.config: dict[str, Any] = {"spa": False}
        self.deploy_requested = False
        self.question: dict | None = None
        self.finish_summary: str | None = None
        self.fail_reason: str | None = None

    def _resolve(self, path: str) -> Path:
        target = (self.staging / path.lstrip("/")).resolve()
        if not str(target).startswith(str(self.staging) + "/") and target != self.staging:
            raise ValueError(f"路径越界: {path}")
        return target


TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "列出暂存区文件树（最多 200 条）",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "读取暂存区内文本文件（截断至 20000 字符）",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "相对路径"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "patch_text",
            "description": "文本级精确替换（old 必须在文件中唯一出现一次）",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old": {"type": "string"},
                    "new": {"type": "string"},
                },
                "required": ["path", "old", "new"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "写入新文件或整体覆盖小文件（≤100KB，仅限文本）",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "decide_config",
            "description": "确定部署配置（是否 SPA 等）",
            "parameters": {
                "type": "object",
                "properties": {
                    "spa": {"type": "boolean", "description": "是否单页应用（前端路由）"},
                    "notes": {"type": "string", "description": "配置理由"},
                },
                "required": ["spa"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "deploy",
            "description": "执行部署上线。仅在满足部署标准后调用。",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ask_user",
            "description": "向用户/对方 Agent 提出结构化问题，任务转入等待输入",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "options": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "可选，供选择的选项列表",
                    },
                },
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finish",
            "description": "任务完成，给出总结",
            "parameters": {
                "type": "object",
                "properties": {"summary": {"type": "string"}},
                "required": ["summary"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fail",
            "description": "拒绝/失败，说明理由（内容违规、无法修复等）",
            "parameters": {
                "type": "object",
                "properties": {"reason": {"type": "string"}},
                "required": ["reason"],
            },
        },
    },
]


def run_local_tool(ctx: ToolContext, name: str, args: dict) -> str:
    """执行本地工具（deploy 由调用方特殊处理）。返回工具结果文本。"""
    try:
        if name == "list_files":
            files = sorted(
                str(p.relative_to(ctx.staging)) for p in ctx.staging.rglob("*") if p.is_file()
            )
            lines = files[:200]
            if len(files) > 200:
                lines.append(f"... 共 {len(files)} 个文件")
            return "\n".join(lines) or "(空目录)"

        if name == "read_file":
            target = ctx._resolve(str(args["path"]))
            if not target.is_file():
                return f"错误：文件不存在 {args['path']}"
            try:
                content = target.read_text(errors="replace")
            except UnicodeDecodeError:
                return "错误：二进制文件不可读"
            if len(content) > MAX_READ_CHARS:
                content = content[:MAX_READ_CHARS] + "\n... (已截断)"
            return content

        if name == "patch_text":
            ctx.patches += 1
            if ctx.patches > MAX_PATCHES_PER_TASK:
                return "错误：修补次数过多，请直接说明问题"
            target = ctx._resolve(str(args["path"]))
            if not target.is_file():
                return f"错误：文件不存在 {args['path']}"
            content = target.read_text(errors="strict")
            old, new = str(args["old"]), str(args["new"])
            count = content.count(old)
            if count != 1:
                return f"错误：old 在文件中出现 {count} 次（要求唯一出现 1 次）"
            target.write_text(content.replace(old, new))
            return f"已修补 {args['path']}"

        if name == "write_file":
            ctx.patches += 1
            if ctx.patches > MAX_PATCHES_PER_TASK:
                return "错误：修补次数过多"
            target = ctx._resolve(str(args["path"]))
            content = str(args["content"])
            if len(content.encode()) > 100 * 1024:
                return "错误：write_file 仅支持 ≤100KB 文本"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
            return f"已写入 {args['path']}"

        if name == "decide_config":
            ctx.config["spa"] = bool(args.get("spa", False))
            return f"配置已确定: spa={ctx.config['spa']}"

        if name == "deploy":
            ctx.deploy_requested = True
            return "部署请求已记录"

        if name == "ask_user":
            ctx.question = {
                "question": str(args["question"]),
                "options": [str(o) for o in args.get("options", [])][:6],
            }
            return "已向用户提问"

        if name == "finish":
            ctx.finish_summary = str(args["summary"])[:2000]
            return "任务完成"

        if name == "fail":
            ctx.fail_reason = str(args["reason"])[:2000]
            return "任务已标记失败"

        return f"错误：未知工具 {name}"
    except (ValueError, HTTPException) as e:
        return f"错误：{e}"
    except Exception as e:  # noqa: BLE001 — 工具错误不能打断 loop
        return f"工具内部错误：{type(e).__name__}"
