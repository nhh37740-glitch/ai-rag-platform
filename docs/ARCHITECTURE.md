# 系统架构说明（面向人类程序员）

## 1. 一句话

一个 **企业研发知识与协作智能体（Dev Knowledge Agent）**：公开中文文档入库 → 向量检索 → DeepSeek/Mock 回答 → 工具与 Skill → 双层记忆 → 聊天界面；并做成 **契约先行 + 源码隔离 + 二进制交付** 的可换模型、存储和连接器的模块化系统。

## 2. 设计模式

| 模式 | 在本系统中的体现 | 具体位置/模块 |
|---|---|---|
| **端口与适配器（六边形）** | 核心只依赖"端口"接口，外部实现是"适配器"，可整体替换 | `LLMProvider`、`VectorStore`、`Storage`、`McpServerClient`；适配器见下 |
| **策略（Strategy）** | 同一操作可有多个可切换实现 | 向量化 `embed`（`fastembed`/`hash`）、LLM（`DeepSeek`/`Mock`） |
| **适配器（Adapter）** | 把异构接口转成统一类型 | `DeepSeekProvider`（OpenAI 兼容→`LLMProvider`）、`normalize_to_tool`（MCP→`ToolDef`） |
| **抽象工厂 / 依赖注入（组合根）** | 主进程集中创建并注入依赖 | `apps/agent-server/server.py` 装配 runtime、vector store、memory 与工具 |
| **门面（Facade）** | 一个薄入口封装复杂编排 | `AgentRuntime.run`（编排循环）、`Storage`（持久层门面） |
| **注册表 / 插件（Registry）** | 动态注册、按名取用 | `ToolRegistry`（`@tool`）、`SkillRegistry`（`SKILL.md`）、`MockMcpServer` |
| **契约 / 按合约设计** | 先定接口与类型，再实现 | `contracts/`（`core_contracts` + `INTERFACE.md` + `API_SCHEMA.json` + `test_contract.py`） |
| **仓储 / DAO** | 持久化访问封装 | `MemoryStore`、`Storage`（SQLite） |
| **模板方法 / 流水线** | 固定步骤、可插拔环节 | RAG：embed→retrieve→context；Agent：记忆/完整 Skill→LLM→按需多次工具调用→写记忆 |
| **职责链** | 依次尝试工具并回传结果 | `AgentRuntime.run` 内的 tool-call 循环 |
| **观察者 / 追踪** | 上下文贯穿 + 事件记录 | `RequestContext` + `TraceStore`/`Span`（`/api/trace/{id}`） |
| **单例** | 全局唯一注册表 | `tool_runtime._GLOBAL` > `default_registry()` |
| **建造者** | 工厂方法组装对象 | `make_memory`/`make_storage`/`make_runtime` |
| **模块/分层隔离 + 二进制交付（部署模式）** | 每模块独立包/成品，集成侧无源码 | `modules-src/` ↔ `artifacts/` + `registry.json` + checksum |

## 3. 模块与接口

> 每模块的 `INTERFACE.md`/`API_SCHEMA.json` 见各自目录；此处为对外摘要。所有模块函数/方法首参为 `RequestContext`（trace/request/user/session）。

### 契约层 `contracts/core_contracts`
共享类型（无实现）：`RequestContext`、`ChatMessage`、`ToolCall`、`ToolDef`、`Citation`、`RetrievalResult`、`MemoryEntry`、`SkillDef`、`SpanEvent`。

### 可观测 `observability`
- `TraceStore.record(ev) / get(trace_id)`
- `Span(ctx, name, store)` / `ASpan(...)`：记录耗时/成败。

### 记忆 `memory`
- `MemoryStore.get/write/search/forget(ctx, namespace, ...)`（session/user 双命名空间，SQLite）
- `make_memory(db_path)`

### 检索 `rag_core`
- `embed(texts)` / `make_embed(backend)`（默认 `fastembed` + `BAAI/bge-small-zh-v1.5`；`hash` 仅显式选择）
- `InMemoryVectorStore.add(source_id, chunks, embeddings) / search(embedding, top_k)`
- `retrieve(ctx, query, store, scope, top_k) -> RetrievalResult`、`build_context(result)`

### Agentic RAG 技能 `rag_skill`
- `RagSkill.tool_definition()` 向 LLM 暴露 `search_knowledge_base`
- `RagSkill.execute(ctx, query, knowledge_base_ids, top_k)` 执行受范围限制的检索，返回结构化引用并记录 `rag` span

### 模型网关 `llm_gateway`
- `LLMProvider.generate(ctx, messages, tools) -> (content, list[ToolCall])` / `stream(...)`
- `DeepSeekProvider(api_key, base_url, model, transport)`、`MockProvider(scenario)`

### 工具运行时 `tool_runtime`
- `@tool(name, description, parameters, context_aware=False)` 注册
- `ToolRegistry.execute(ctx, call, runtime_context)` 可为受信工具注入当前知识库范围与会话消息

### 技能运行时 `skill_runtime`
- `SkillRegistry.load_dir(path) / list(ctx) / load(ctx, name) / render(ctx, query)`，选中后惰性加载完整 SKILL.md

### Agent 编排 `agent_runtime`
- `AgentRuntime.run(ctx, user_input, knowledge_base_ids) -> str`（记忆/历史/完整 Skill→LLM→工具循环→写记忆；循环上限默认 10 轮且不得配置小于 10）
- `make_runtime(...)`

### MCP 网关 `mcp_gateway`
- `McpServerClient.connect/list_tools/call_tool`
- `MockClient`（v1 mock）、`normalize_to_tool(mcp_tool) -> ToolDef`

### MCP 服务器 `mcp_servers`
- `MockMcpServer.register(tools)/call(name, args)`、`build_default_server()`
- 真实：`github.build_github_server(repo, token, client)`（`get_commits`/`list_issues`/`get_commit`）
- CLI `python -m mcp_servers`（stdio 的 `tools/list`、`tools/call`；`MCP_GITHUB_REPO` 切真实）

### 评测 `evaluation`
- `evaluate_qa(ctx, qa) -> dict`（Recall/Precision/Faithfulness/Answer Relevance）
- `llm_as_judge(ctx, provider, question, answer, context) -> int`
- `evaluate_agent(ctx, trajectory) -> dict`

### 入库 `ingestion`
- `parse(path)` / `chunk(texts, size, overlap)` / `build_index(ctx, dir, store, embed_fn)`
- CLI `python -m ingestion <dir> --out index.json`（独立进程产索引，主进程读索引）

### 统一存储 `storage`
- `Storage.memory_*/add_documents/search_documents/save_eval/load_eval`
- `make_storage(db_path, memory_store, vector_store)`（组合 memory + vector + SQLite，接口与 pgvector 同构）

### 主进程 `apps/agent-server/server.py`
FastAPI：`GET /`（聊天页）、`GET /api/demo`（CMRC2018 状态与示例问题）、`GET/POST /api/notebooks`（列出/创建笔记本）、`POST /api/notebooks/{id}/files`（上传并转 Markdown）、`POST /api/chat`、`GET /api/chat/stream`（携带知识库选择的 SSE）、`GET /api/trace/{trace_id}`。

## 4. 运行结构与数据流

```text
浏览器/客户端 ──SSE/JSON──> agent-server(FastAPI, 组合根)
                            │ AgentRuntime(编排)
                            ├─ llm_gateway  → DeepSeek/Mock
                            ├─ memory       → SQLite(会话+用户)
                            ├─ rag_skill    → search_knowledge_base 工具→rag_core(FastEmbed+BGE)
                            ├─ skill_runtime→ 选择并加载完整 SKILL.md
                            ├─ tool_runtime → RAG/受限文件/对话入库工具
                            └─ observability→ TraceStore(/api/trace)
项目知识库：data/kb（内置 CMRC2018 + 用户笔记本；上传文件统一转为 Markdown）
独立进程：ingestion(可产 data/index.json)      mcp_servers(stdio MCP)
持久化：SQLite + 本地向量库（storage 接口可切 pgvector）
```

前端与产物：
- **上传适配**：`apps/agent-server/document_upload.py` 负责类型/大小校验、临时文件清理并调用 ingestion 转换 Markdown。
- **Web 前端**：`apps/agent-server/webui/index.html` 负责页面结构，`knowledge_demo.css` 负责样式，`knowledge_demo.js` 负责笔记本创建、文件上传、知识库选择、示例问题和 SSE 聊天。
- **编译产物**：进程内模块由 `scripts/compile_extension_modules.py` 编成 `.pyd`；独立进程由 `scripts/compile_service_executables.ps1` 编成 `bin/*.exe`；`scripts/package_release_artifacts.py` 生成发布元数据与注册表。

## 5. 关键设计决策

- **契约先行**：接口/类型先用 `contracts/` 定死，各模块按 `INTERFACE.md` 实现，减少联调返工。
- **源码隔离 + 二进制交付**：实现源码在 `modules-src/`，集成侧只消费 `artifacts/` 下二进制、契约与 checksum；源码模式和二进制模式分别由两个 `verify_*_runtime.py` 入口验收。
- **可替换而不重写**：换模型（DeepSeek↔OpenAI）、换向量/存储（FastEmbed 模型↔显式 hash 开发后端、SQLite↔pgvector）、换技能/工具、换 MCP 连接器，均只改一个适配器/注册项。
- **演示数据边界**：CMRC2018 子集位于 `data/kb/cmrc2018-demo/`，通过正式知识库链路加载；它仅用于展示中文知识导入、检索、回答与引用，不承担向量模型评测。

## 6. 运行 / 测试

```bash
.\.venv\Scripts\python.exe -m uvicorn --app-dir apps/agent-server server:app --port 8000
.\.venv\Scripts\python.exe scripts/verify_source_runtime.py
.\.venv\Scripts\python.exe scripts/verify_compiled_runtime.py
```
