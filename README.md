# Dev Knowledge Agent

基于 **RAG、MCP、Agent Skills、Function Calling 与双层记忆** 的模块化企业研发知识与协作智能体系统。它以"契约先行 + 源码隔离 + 二进制交付"落地：集成侧只消费接口契约与编译后成品，看不到各模块实现源码。

## 演示能力（6 个场景）

1. **XX API 如何认证？** → RAG + 引用
2. **昨天的故障跟历史哪次最像？** → Memory + RAG + Issue 检索
3. **帮我按公司 Bug 流程分析** → `bug-triage` Skill
4. **建立一个 P1 Bug** → Function Calling
5. **看看最近相关 commit** → MCP 工具（mock 连接器）
6. **上次处理到哪了？** → User/Session 记忆

## 结构

```text
contracts/       # 契约层（接口/共享类型，唯一共享"源码"）
modules-src/     # 各模块源码仓库（对集成侧不可见）
artifacts/       # 版本化成品 + 契约文档 + checksum
apps/agent-server# 主进程：FastAPI + Agent 编排 + 聊天页
data/            # 知识库、SQLite 数据
skills/          # SKILL.md 技能目录
scripts/         # demo / integration / eval / build_artifacts
```

12 个独立 Python 包：`core_contracts/observability/memory/rag_core/llm_gateway/tool_runtime/skill_runtime/agent_runtime/mcp_gateway/mcp_servers/evaluation/storage`。

## 运行

```bash
# 环境
uv venv .venv && uv pip install -e contracts -e modules-src/observability -e modules-src/memory -e modules-src/rag_core -e modules-src/llm_gateway -e modules-src/tool-runtime -e modules-src/skill-runtime -e modules-src/agent_runtime -e modules-src/evaluation -e modules-src/ingestion -e modules-src/mcp-gateway -e modules-src/mcp-servers -e modules-src/storage fastapi uvicorn pytest python-docx

# 启动（默认 Mock；设 DEEPSEEK_API_KEY 用真实 DeepSeek）
.\.venv\Scripts\python.exe -m uvicorn --app-dir apps/agent-server app:app --port 8000

# 用独立进程产索引（供主进程加载；SKIP_INDEX 存在时 app 回退为启动时内联建索引）
.\.venv\Scripts\python.exe -m ingestion data/kb --out data/index.json

# 6 个演示
.\.venv\Scripts\python.exe scripts/demo.py

# 端到端 + 评测
.\.venv\Scripts\python.exe scripts/integration_test.py
.\.venv\Scripts\python.exe scripts/eval_run.py          # 生成 docs/eval_report.md

# 测试（全部模块）
.\.venv\Scripts\python.exe -m pytest modules-src -q

# 生成 artifacts + registry
.\.venv\Scripts\python.exe scripts/build_artifacts.py

# 一键验收（pytest → 集成 → 评测 → artifacts → binary 演示）
.\.venv\Scripts\python.exe scripts/ci.py

# 二进制交付：MSVC 环境下批量 cythonize → artifacts/<pkg>/<version>/<pkg>/*.pyd
cmd /c "call \"C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat\" && .\.venv\Scripts\python.exe scripts/build_binary_all.py"

# 纯编译产物运行整条 Agent 链路（无源码）
.\.venv\Scripts\python.exe scripts/demo_compiled.py
```

## 说明

- 默认离线可跑：`MockProvider` 兜底，`DEEPSEEK_API_KEY` 存在时自动切真实 `DeepSeekProvider`。
- 在仓库根 `.env` 写入 `DEEPSEEK_API_KEY=sk-...` 即用真实 DeepSeek（已实测 RAG+工具调用端到端）；`.env` 不入库。
- 向量化默认本地兜底；`.env` 已开 `RAG_EMBED=fastembed` → 用中文优化的 **`BAAI/bge-small-zh-v1.5`**（首次自动下载）；`scripts/ci.py` 强制离线（Mock + hash）保证可复现。
- MCP 连接器：本地 mock 默认；设 `MCP_GITHUB_REPO=owner/repo`（可选 `GITHUB_TOKEN`）即用真实 GitHub 连接器；`scripts/mcp_github_demo.py` 演示真实拉取 commits/issues。存储用 SQLite + 本地向量库（无需 PostgreSQL）。

设计模式、模块清单与各模块接口的**人类可读架构说明**见 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)。

前端与编译产物：
- **Web 前端**：`GET http://127.0.0.1:8000/` 即聊天页（SSE 流式）；非纯命令行。
- **编译产物**：进程内模块已可由 `scripts/build_binary_all.py` 编成 `.pyd`；独立进程入口由 `scripts/build_exe.ps1` 编成 `bin/*.exe`（已生成 `bin/mcp_servers.exe`；ingestion_worker 加 `-All`）。运行时也可直接 `python -m mcp_servers`、`python -m ingestion`。
- 向量化用本地兜底 embed（可换 BGE）；存储默认 SQLite + 本地向量库，接口与 PostgreSQL+pgvector 同构。
- 聊天页用 SSE（`/api/chat/stream`），`/api/chat` 也可 JSON 调用；`/api/trace/{trace_id}` 看全链路。
- 二进制交付见 [`docs/build_binary.md`](docs/build_binary.md)；总体计划见 [`docs/PLAN.md`](docs/PLAN.md)；约定见 [`AGENTS.md`](AGENTS.md)。
