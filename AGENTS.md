# Repository Guidelines

## 项目目的

本仓库用于构建 **企业研发知识与协作智能体系统（Dev Knowledge Agent）** 并持续对照目标岗位完善简历。核心能力是"会问答、会调工具、会走流程、记得住上下文"，并把它做成**契约先行 + 源码隔离 + 二进制交付**的模块化系统——集成/主 Agent 只拿到接口契约与编译后的二进制，看不到各模块实现源码。

> 唯一事实来源是 [`docs/PLAN.md`](docs/PLAN.md)。改方案先改它，再动代码。

## 结构约定

```text
contracts/       # 契约层（唯一共享"源码"）：core-contracts + INTERFACE.md + API_SCHEMA.json + test_contract.py
modules-src/     # 各模块源码仓库（对集成 Agent 不可见，仅对应 subagent 有写入权）
artifacts/       # 集成 Agent 只读：模块/版本/ 下的二进制 + 契约文档 + checksum
registry.json    # 各模块版本 + checksum 索引
apps/            # 集成 Agent 编写：agent-server(FastAPI) + web-ui + ingestion/MCP 调用
docs/            # PLAN.md 与 architecture/ 说明
```

命名约定：模块用 `kebab-case`（如 `rag-core`、`tool-runtime`）；每个模块是一个独立 git 仓库，含 `README.md`、`INTERFACE.md`、`API_SCHEMA.json`、`CHANGELOG.md`、`VERSION`、`tests/`。

## 架构原则

- **契约先行**：所有接口先写进 `contracts/`，类型化签名固定后再实现。
- **源码隔离**：实现源码放 `modules-src/`，集成侧只消费 `artifacts/` 里的二进制与契约。
- **二进制交付**：进程内模块用 mypyc（默认）/Cython（回退）编译成 `.pyd/.so`；`ingestion-worker`、`mcp-servers` 用 Nuitka 生成 `.exe`，或仅暴露 `POST /ingest`、`POST /evaluate`、MCP `tools/call`。
- **进程/线程**：`agent-server` 内走接口直调 + asyncio/`asyncio.to_thread`；真正独立的模块（ingestion-worker、MCP servers）才拆成独立进程。
- **存储**：统一 `storage` 接口，默认 SQLite 元数据 + 本地向量库（FAISS/Chroma），接口与 PostgreSQL+pgvector 同构，可无痛切换。
- **可观测**：所有模块接收 `RequestContext(trace_id, request_id, user_id, session_id)`，打结构化日志 + span 耗时；`GET /api/trace/{trace_id}` 看全链路。

## 构建、测试与运行

每个模块在自己仓库内 `pytest`，编译成二进制并写 `checksum` 进 `artifacts/` 与 `registry.json`。集成侧只跑契约测试与端到端：

```bash
# 契约/端到端（在集成侧）
python -m pytest contracts/test_contract.py
python scripts/verify_source_runtime.py
python scripts/verify_compiled_runtime.py
```

## 提交与 PR 规范
- 使用 Conventional Commits：`feat:` `fix:` `docs:` `test:` `build:`。
- 模块改动 = 独立仓库一次提交 + bump `VERSION` + 更新 `CHANGELOG.md` + 重建二进制与 `checksum`。
- PR 描述需说明：模块实现什么、接口是否变化、如何运行、对应哪条岗位要求。
- 集成侧改动只允许触碰 `contracts/`、`apps/`、`registry.json`、根 `README`，不得修改 `modules-src/` 或其他模块实现。
- 提交前检查：`AGENTS.md` 与 `docs/PLAN.md` 是否为最新事实；所有改动链路（版本、checksum、契约测试）一致。
