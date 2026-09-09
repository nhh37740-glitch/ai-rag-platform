# 企业研发知识与协作智能体系统（Dev Knowledge Agent）实施计划

> 本文件是执行的唯一事实来源；主 Agent 与各 subagent 均以它为准。任何改动先回到这里。

## 目标

构建一个"会问答、会调工具、会走流程、记得住上下文"的企业研发助手，并以**契约先行 + 源码隔离 + 二进制交付**落地——集成/主 Agent 只拿到接口契约与编译后的二进制，看不到各模块实现源码，从而无法"顺手改"模块内部。

6 个贯穿全栈的演示：API 认证问答（RAG+引用）、历史相似故障分析（Memory+RAG+MCP）、Bug 流程分析（`bug-triage` Skill）、建 P1 Bug（Function Calling）、查最近 commit（MCP）、"上次处理到哪了"（用户/会话记忆）。

## 仓库 / 工件布局（谁只能看到什么）

```
<workspace>/
  contracts/            # 契约层，唯一共享"源码"：core-contracts + INTERFACE.md + API_SCHEMA.json + test_contract.py
  modules-src/          # 各模块源码仓库（对集成 Agent 不可见；仅对应 subagent 有写入权）
    rag-core/  memory/  llm-gateway/  rag-core/  tool-runtime/  mcp-gateway/
    skill-runtime/  agent-runtime/  observability/  evaluation/  ingestion/  mcp-servers/
  artifacts/            # 集成 Agent 只读：按 模块/版本/ 存放成品
    rag-core/1.2.0/rag_core.pyd + INTERFACE.md + API_SCHEMA.json + VERSION + CHANGELOG.md + test_contract.py + checksum.sha256
    ...
  registry.json         # 各模块版本 + checksum 索引，集成侧据此 pin 版本
  apps/                 # 集成 Agent 编写：agent-server(FastAPI) + web-ui + ingestion 调用 + MCP 调用
```

- `contracts/`：接口与 schema（无实现），所有 subagent 与集成 Agent 可见、可校验。
- `modules-src/`：实现源码，集成 Agent 不检出、不消费；每个模块是一个独立 git 仓库。
- `artifacts/`：集成侧只从这里取版本化二进制 + 契约文档 + 契约测试。
- 已知限制：Codex 子 Agent 共享文件系统，机器级隔离需容器（本地无 Docker）；本方案通过"集成侧只 import 二进制 + 工作区不放实现源码 + 仓库边界"实现操作/进程级隔离。

## 编译与交付形态

- **进程内模块**（`rag-core`、`memory`、`llm-gateway`、`tool-runtime`、`mcp-gateway`、`skill-runtime`、`agent-runtime`、`observability`、`evaluation`）：编译成可 import 的扩展模块，默认 **mypyc**（typed Python → `.pyd`/`.so`），遇不支持的特性回退 **Cython**（`.pyx`）；Windows 产物为 `.pyd`。
- **独立进程模块**（`ingestion-worker`、`mcp-servers`）：用 **Nuitka** 编译成独立可执行文件（`.exe`），或经 `POST /ingest`、`POST /evaluate`、MCP `tools/call` 暴露，集成侧只见 API、不见源码。
- **契约包**（`core-contracts`）：纯类型/契约（Pydantic + `RequestContext`），作为共享源码包，不编译隔离。
- 每件产物必须带 `VERSION`、`CHANGELOG.md`、`checksum.sha256`、`API_SCHEMA.json`，并登记进 `registry.json`。

## 关键接口与数据流

- **契约**：`RequestContext(trace_id, request_id, user_id, session_id)` 贯穿所有模块；各模块公开 facade 用类型化签名写死，供集成侧 `from rag_core import RagClient` 直调。
- **llm-gateway**：`LLMProvider.generate/stream/tool_call`；`DeepSeekProvider` 首个实现（`deepseek-chat` 函数调用，`deepseek-reasoner` 可选）；预留 OpenAI/Anthropic/Local。
- **rag-core**：`retrieve(query, scope) -> RetrievalResult`（rewrite→retrieve→rerank→context build→Citations），对 embedding/向量库/MCP/Skill/前端无感知。
- **memory**：`SessionMemory`、`UserMemory` 两命名空间，`get/search/write/forget`；仅 memory 写库。
- **tool-runtime + mcp-gateway**：`@tool` 函数与 MCP 工具归一为同一 `Tool`；mcp-gateway 负责 discovery/connect/list/call/materialize。
- **skill-runtime**：`skills/*/SKILL.md`（frontmatter name/description + 指令 + 可选 `scripts/references/assets`），按需加载。
- **agent-runtime**（最薄）：理解请求→取记忆→选 Skill→定 RAG/Tool→调 LLM→执行 tool→再调 LLM→写记忆→输出。
- **observability**：跨模块结构化日志 + span 耗时，`GET /api/trace/{trace_id}` 看全链路；预留 Phoenix/OTel 适配器，v1 用内存 trace + 日志。
- **存储**：`storage` 接口统一用户/会话/记忆/文档元数据/向量/评测结果；默认 **SQLite 元数据 + 本地向量库（FAISS/Chroma）**，接口与 PostgreSQL+pgvector 同构，可无痛切换；本地 BGE（默认 `bge-small-zh`）。

## 构建与集成工作流（主 agent 指挥，一模块一 subagent，一仓库）

1. **契约先行**：主 agent 写 `contracts/`（core-contracts + 各模块 `INTERFACE.md`/`API_SCHEMA.json`/`test_contract.py`），定死接口与依赖方向；生成各模块独立 git 仓库与 `artifacts/`/`registry.json` 骨架；此步产出即各 subagent 的任务书。
2. **模块开发（源码仓库内）**：主 agent 为每个模块 spawn 一位 subagent，只给该模块仓库路径 + 契约；子 Agent 实现、写单测（mock 下游）、编译二进制、算 checksum、bump 版本、发布到 `artifacts/<模块>/<版本>/` 并登记 `registry.json`；不得改契约或其他模块。
3. **集成（仅契约 + 二进制 + 应用）**：主 agent 从 `artifacts/` 取 pin 版本并校验 checksum，用接口契约在 `apps/agent-server` 里直调各 `.pyd`，组 `web-ui` 与 `ingestion`/`MCP` 调用，跑各 `test_contract.py`（对二进制）与端到端冒烟。
4. **评测与收尾**：`evaluation` 对 6 个演示任务出基线报告；编译各包 wheel/exe；补 `docs/architecture/` 与根 README。

## 测试计划与验收

- **单模块（源码仓库）**：pytest 单元测试（mock LLM/向量库/外部系统），编译前全绿。
- **契约测试**：集成侧对每个二进制跑 `test_contract.py`（类型/出参/异常一致）。
- **集成/端到端**：本地起 agent-server + ingestion-worker(.exe) + mock MCP + SQLite，跑"上传文档→索引→提问→RAG+工具+记忆→作答"；6 个演示任务逐一通过。
- **评测**：输出 Retrieval Recall/Precision、Faithfulness、Answer Relevance、Tool/Skill 选择准确率、Memory recall、任务成功率、延迟/Token 成本（参考 DeepEval 分层）。
- **验收**：所有模块版本化带 checksum、契约测试全绿、6 个演示端到端通过、评测报告可复现；集成侧工作区无任何模块实现源码。

## 假设与默认

- Python 3.11+、uv；本地无 Docker，故不做容器级隔离；编译用 mypyc（默认）/Cython（回退）生成 `.pyd/.so`，进程模块用 Nuitka 生成 `.exe`；Windows 平台。
- 除 DeepSeek 聊天 API 外无外部依赖；存储默认 SQLite + 本地向量库，走 `storage` 接口以便切 pgvector；BGE 默认 `bge-small-zh`。
- `DEEPSEEK_API_KEY` 经 `.env` 注入，不入库；单用户单租户演示；可选简单 API key。
- MCP connector（Git/Issue/工单）v1 用本地 mock，接口与真实连接器一致，便于日后插真。
- "SKILL" 采用 Agent Skills 的 SKILL.md 开放格式；前端为 agent-server 托管单页聊天（SSE）。

## 实现状态（2026-09-10）

已落地并跑通（离线纯 Python 版）：

- 11 个独立包：`core_contracts`、`observability`、`memory`、`rag_core`、`llm_gateway`、`tool_runtime`、`skill_runtime`、`agent_runtime`、`mcp_gateway`、`mcp_servers`、`evaluation`。
- 主进程 `apps/agent-server`：FastAPI + Agent 编排 + 聊天页（`/api/chat`、`/api/kb/ingest`、`/api/trace/{id}`）。
- 6 个演示场景全部通过；20 个单元测试全绿；评测基线生成于 `docs/eval_report.md`。
- 源码隔离按"集成侧只 import 二进制 + 工作区不放实现源码"原则落地，`build_artifacts.py` 产出 `artifacts/<pkg>/<version>/` + `registry.json` + checksum。
- 二进制交付已打通：本机有 MSVC，**Cython** 可把模块编译成 `.pyd`；已用 observability 做证明——编译产物单独置于 `artifacts/observability/0.1.0/observability/`（无 `.py`），`scripts/binary_demo.py` 直接 `import` 该 `.pyd` 并运行成功。多模块批量 `.pyd/.so/.exe` 编译是后续批次步骤，步骤见 `docs/build_binary.md`。
- `ingestion` 已可作**独立进程**：`python -m ingestion <docs> --out data/index.json` 产索引，主进程 `_load_kb` 优先加载；聊天前端走 **SSE**（`/api/chat/stream`）。
- 一键验收门禁 `scripts/ci.py`（pytest→集成→评测→artifacts→binary 演示）已跑通并输出 `CI CHECKPOINT: ALL GREEN`。
- **整条 Agent 链路可纯用编译产物运行**：`scripts/build_binary_all.py` 在 MSVC 下把 11 个模块批量 cythonize 成 `.pyd` 归入 `artifacts/<pkg>/<version>/<pkg>/`，`scripts/demo_compiled.py` 只从 artifacts 加载并跑通提问→检索→作答，输出 `COMPILED_AGENT_OK`。
- 新增 **`storage` 统一持久层**模块：组合 memory + vector_store + SQLite（评测结果），暴露 `Storage` 接口（记忆/文档向量/评测），与 PostgreSQL+pgvector 同构可切换；测试通过（共 12 个包，22 条测试，CI ALL GREEN）。
- **真实 DeepSeek 端到端已验证**（2026-09-10，提供 key 后）：`.env` 注入 `DEEPSEEK_API_KEY`，app 自动切 `DeepSeekProvider`；RAG 问答引用了知识库（§2 认证/§3 超时/§4 限流），工具调用 `create_issue` 返回 issue 编号并给多步答复。期间修复了"工具调用后 assistant 消息需回带 `tool_calls`"（否则 DeepSeek 400）。`scripts/demo.py` 在有 `.env` 时即走真实模型。
- **评测基线已切到真实 DeepSeek**：`scripts/eval_run.py` 在有 `.env` 时用真实模型作答与 LLM-as-Judge，最新 `avg_recall=1.0`、`avg_llm_judge=7.67`（`docs/eval_report.md`）。并统一了 ingestion 产出的源 ID（`stem`，无扩展名）与评测期望一致。
- **真实 embedding（默认=中文优化）**：`rag_core.embed` 用 `RAG_EMBED=fastembed` 加载 **`BAAI/bge-small-zh-v1.5`**（512 维，中文语义强，本机已下载），`hash` 兜底；`.env` 已开。真实 DeepSeek + bge-small-zh 下评测通过（recall 1.0、LLM-judge 7.33）。
- `scripts/ci.py` 强制 `DEEPSEEK_API_KEY=''`、`RAG_EMBED=hash`，使 CI 离线确定性（不依赖 key/网络）。
- **真实 MCP 连接器已实现并验证**：`mcp_servers/github.py` 用 httpx 调 **GitHub 公共 API**（无 token 可用，`GITHUB_TOKEN` 提升限额/私有库），`get_commits`/`list_issues`/`get_commit` 已从 `octocat/Hello-World` 取回真实数据；`scripts/mcp_github_demo.py` 可复现。stdio MCP 服务设 `MCP_GITHUB_REPO=owner/repo` 即切真实连接器，否则本地 mock。企业内网工单连接器以同样插拔方式接入（需提供服务 host/token）。
- 存储保持 **SQLite + 本地向量库**（无需 PostgreSQL）；企业内网工单系统目前不存在，故该连接器不做（machinery 已就绪，接真实系统时插拔即可）。
