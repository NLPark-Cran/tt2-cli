# AGENTS.md — tt2-cli

> 本文件是 coding agent 在本仓库工作时必须遵守的约定。修改任何下列内容时，请同步更新本文件。

## 项目是什么

tt2-cli 是 `?hub.tt2.li` 静态托管网络的工具包：人类用控制台（free.hub.tt2.li）、Agent 用 `tt2` CLI，把静态站点部署到边缘节点。**核心安全模型：用户的 Agent 永远不直接接触服务提供机**——所有部署请求都由服务端的「猹询码」（cran-code lite 分支，glm-5.3-flash）中介处理。

## 仓库结构

| 目录 | 说明 | 技术栈 |
|---|---|---|
| `api/` | 控制面 API（任务、认证、配额、部署执行器、猹询码接入层） | FastAPI + SQLAlchemy 2 + Alembic + Redis |
| `cli/` | `tt2` 单文件 Bash CLI 与 install.sh | Bash（仅依赖 curl/tar），shellcheck 全绿 |
| `web/` | 官网 + 控制台（free.hub.tt2.li） | Astro 5 + Tailwind CSS v4，纯静态输出 |
| `skill/` | 发布给 Agent 的 SKILL.md | Markdown |
| `deploy/control/` | 控制面部署物：systemd unit、nginx 站点、.env.example | - |
| `deploy/edge/` | 边缘节点 bootstrap.sh（Caddy、deploy 用户、sudoers） | Bash |
| `docs/` | 架构、节点接入、内容政策、DNS 指南 | Markdown |

猹询码 agent loop 本体在 `NLPark-Cran/cran-code` 的 `lite` 分支；`api/app/chaxunma/` 只是接入胶水层。

## 代码规范（CI 强制）

- **Python**：uv 管理环境；ruff lint+format（line-length 100）；pyright basic；pytest 覆盖率 ≥80%；结构化日志用 structlog，禁止 print。
- **API**：前缀 `/api/v1`；错误统一 `{"error": {"code", "message", "details"}}`；写操作支持 `Idempotency-Key`；列表用 cursor 分页。
- **Bash**：`set -euo pipefail`；shellcheck；退出码 0 成功 / 2 参数 / 3 认证 / 4 配额 / 5 服务端。
- **Git**：Conventional Commits；trunk-based；CI 全绿才合入。

## 安全红线（违反 = 拒绝合入）

1. 任何 Token / API Key **不进日志、不进 git**；落库一律哈希（CLI token）或 Fernet 加密（TokenDance key）。
2. 所有外部输入必须经 pydantic 校验。
3. tar 解压必须防路径逃逸：白名单扩展名、拒绝符号链接、拒绝绝对路径与 `..`。
4. 猹询码工具白名单之外的能力（任意 shell、网络、写暂存区之外）一律禁止。
5. 边缘节点只发静态文件：不部署任何解释器/运行时。

## 本地开发

```bash
cd api && uv sync && uv run pytest          # 控制面
shellcheck cli/tt2 cli/install.sh           # CLI
cd web && npm i && npm run build            # 官网
```
