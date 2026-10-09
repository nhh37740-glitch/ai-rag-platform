# 系统架构说明（面向人类程序员）

## 1. 一句话

一个研发文档问答原型：文档入库 → 模型选择检索工具 → 在选定笔记本内查资料 → 返回来源与答案 → 查看 trace。部署保留接口规范先行与二进制边界。面试阅读顺序见 [`INTERVIEW.md`](INTERVIEW.md)，当前验收与未完成能力以 [`PLAN.md`](PLAN.md) 文末核对为准。

## 当前分层（2026-10-09）

apps/web 只负责静态网页和 API 调用；apps/agent-server 只装配 AgentService、RagService、DataService。三个中间包各自构造本域一级模块；跨域只通过 core_specifications 中的 Protocol 注入。

| 域 | 中间包 | 一级实现 |
|---|---|---|
| AGENT | agent-facade | agent-runtime、llm-gateway、skill-runtime、tool-runtime；其余 AGENT 叶子保留独立能力 |
| RAG | rag-facade | rag-core、rag-tools、ingestion |
| 数据库 | data-facade | memory、storage（SQLite 向量和 JSON 状态） |

源码与二进制各跑一次行为测试；最终服务仍拒绝从源码加载业务模块。完整 API 和验收输入/断言见 specifications/DOMAIN_INTERFACES.md。其余章节描述各一级模块能力。

## 2. 设计模式

| 模式 | 在本系统中的体现 | 具体位置/模块 |
|---|---|---|
| **端口与适配器（六边形）** | 核心只依赖"端口"接口，外部实现是"适配器"，可整体替换 | `LLMProvider`、`VectorStore`、`Storage`、`McpServerClient`；适配器见下 |
| **策略（Strategy）** | 同一操作可有多个可切换实现 | 向量化 `embed`（`fastembed`/`hash`）、LLM（`DeepSeek`/`Mock`） |
| **适配器（Adapter）** | 把异构接口转成统一类型 | `DeepSeekProvider`（OpenAI 兼容→`LLMProvider`）、`normalize_to_tool`（MCP→`ToolDef`） |
| **抽象工厂 / 依赖注入（组合根）** | 主进程集中创建并注入依赖 | `apps/agent-server/server.py` 装配三个中间包，中间包构造域内一级实现 |
| **门面（Facade）** | 一个薄入口封装复杂编排 | `AgentRuntime.run`（编排循环）、`Storage`（持久层门面） |
| **注册表 / 插件（Registry）** | 动态注册、按名取用 | `ToolRegistry`（`@tool`）、`SkillRegistry`（`SKILL.md`）、`MockMcpServer` |
| **接口规范 / 按合约设计** | 先定接口与类型，再实现 | `specifications/`（`core_specifications` + `INTERFACE.md` + `API_SCHEMA.json` + `test_specification.py`） |
| **仓储 / DAO** | 持久化访问封装 | `MemoryStore`、`Storage`（SQLite） |
| **模板方法 / 流水线** | 固定步骤、可插拔环节 | RAG：embed→retrieve→context；Agent：记忆/完整 Skill→LLM→按需多次工具调用→写记忆 |
| **职责链** | 依次尝试工具并回传结果 | `AgentRuntime.run` 内的 tool-call 循环 |
| **观察者 / 追踪** | 上下文贯穿 + 事件记录 | `RequestContext` + `TraceStore`/`Span`（`/api/trace/{id}`） |
| **单例** | 全局唯一注册表 | `tool_runtime._GLOBAL` > `default_registry()` |
| **建造者** | 工厂方法组装对象 | `make_memory`/`make_storage`/`make_runtime` |
| **模块/分层隔离 + 二进制交付（部署模式）** | 每模块独立包/成品，集成侧无源码 | `modules-src/` ↔ `artifacts/` + `registry.json` + checksum |

## 3. 模块与接口

> 已发布接口以 `specifications/API_SCHEMA.json` 为准；请求级操作把 `RequestContext` 作为首参，构造器与纯工具函数按各自接口规范定义。

### 接口规范层 `specifications/core_specifications`
共享类型（无实现）：`RequestContext`、`ChatMessage`、`ToolCall`、`ToolDef`、`Citation`、`RetrievalResult`、`MemoryEntry`、`SkillDef`、`SpanEvent`。

### 可观测 `observability`
- `TraceStore.record(span) / get(trace_id)`
- `Span(ctx, name, store=None)` / `ASpan(...)`：记录耗时/成败。

### 记忆 `memory`
- `MemoryStore.get/write/search/forget(ctx, namespace, ...)`（session/user 双命名空间，SQLite）
- `make_memory(db_path)`

### 检索 `rag_core`
- `embed(texts)` / `make_embed(backend)`（默认 `fastembed` + `BAAI/bge-small-zh-v1.5`；`hash` 仅显式选择）
- `InMemoryVectorStore.add(source_id, chunks, embeddings) / search(embedding, top_k)`
- `retrieve(ctx, query, store, scope, top_k) -> RetrievalResult`、`build_context(result)`
- 检索原语：`keyword_search`（纯词面，不加载模型）、`hybrid_search`（向量+词面 RRF 融合）、`list_documents`、`read_document`

### RAG 工具模块 `rag_tools`
- `RagTools.tool_definitions()` 向 LLM 暴露五个知识库工具：`search_knowledge_base`、`hybrid_search_knowledge_base`、`keyword_search_knowledge_base`、`list_knowledge_documents`、`read_knowledge_document`
- 每个方法都以当前请求的知识库范围执行检索，返回结构化引用并记录带 `tool` 字段的 `rag` span；`read_knowledge_document` 拒绝范围外 `source_id`
- 提示词层面的检索顺序与回退规则在 `skills/rag-retrieval/SKILL.md`

### 模型网关 `llm_gateway`
- `LLMProvider.generate(ctx, messages, tools) -> (content, list[ToolCall])` / `stream(...) -> AsyncIterator[str]`
- `DeepSeekProvider(api_key, base_url, model, transport)`、`MockProvider(scenario)`

### 工具运行时 `tool_runtime`
- `@tool(name, description, parameters, context_aware=False)` 注册
- `ToolRegistry.execute(ctx, call, runtime_context)` 可为受信工具注入当前知识库范围与会话消息

### 技能运行时 `skill_runtime`
- `SkillRegistry.load_dir(path) / list(ctx=None) / load(ctx, name) / render(ctx, query)`，选中后惰性加载完整 SKILL.md

### Agent 编排 `agent_runtime`
- `AgentRuntime.run(ctx, user_input, knowledge_base_ids) -> str`（记忆/历史/完整 Skill→LLM→工具循环→写记忆；循环上限默认 10 轮且不得配置小于 10；提示词要求已选择知识库时所有问题先检索，执行器最多提醒两次，尚非严格成功闸门）
- `make_runtime(...)`

### MCP 网关 `mcp_gateway`
- `McpServerClient.connect/list_tools/call_tool`
- `MockClient`（v1 mock）、`normalize_to_tool(mcp_tool) -> ToolDef`

### MCP 服务器 `mcp_servers`
- `MockMcpServer.register(tools)/call(name, args)`、`build_default_server()`
- 真实：`github.build_github_server(repo, token, client)`（`get_commits`/`list_issues`/`get_commit`）
- CLI `python -m mcp_servers`（stdio 的 `tools/list`、`tools/call`；`MCP_GITHUB_REPO` 切真实）

### 评测 `evaluation`
- `evaluate_qa(ctx, qa_set) -> dict`（Recall/Precision/Faithfulness/Answer Relevance）
- `llm_as_judge(ctx, provider, question, answer, context) -> int`
- `evaluate_agent(ctx, trajectory) -> dict`

### 入库 `ingestion`
- `parse(path)` / `chunk(texts, size, overlap)` / `build_index(ctx, docs_dir, store, embed_fn)`
- CLI `python -m ingestion <dir> --out index.json`（独立进程产索引，主进程读索引）

### 统一存储 `storage`（未接入 Web）
- `Storage.memory_*/add_documents/search_documents/save_eval/load_eval`
- `make_storage(db_path, memory_store, vector_store)`（组合 memory + vector + SQLite 门面；没有 pgvector 适配器，也未进入当前发布注册表）

### 主进程 `apps/agent-server/server.py`
FastAPI：`GET /`（聊天页）、`GET /api/demo`（CMRC2018 状态与示例问题）、`GET/POST /api/notebooks`（列出/创建笔记本）、`POST /api/notebooks/{id}/files`（上传并转 Markdown）、`POST /api/chat`、`GET /api/chat/stream`（携带知识库选择的 SSE）、`GET /api/trace/{trace_id}`。

## 4. 运行结构与数据流

```text
浏览器/客户端 ──SSE/JSON──> agent-server(FastAPI, 组合根)
                            │ AgentRuntime(编排)
                            ├─ llm_gateway  → DeepSeek/Mock
                            ├─ memory       → SQLite(会话+用户)
                            ├─ rag_tools    → 五个知识库检索工具 → rag_core(FastEmbed+BGE)
                            ├─ skill_runtime→ 选择并加载完整 SKILL.md
                            ├─ tool_runtime → RAG/受限文件/对话入库工具
                            └─ observability→ TraceStore(/api/trace)
项目知识库：data/kb（内置 CMRC2018 + 用户笔记本；上传文件统一转为 Markdown）
独立进程：ingestion(可产 data/index.json)      mcp_servers(stdio MCP)
持久化：SQLite MemoryStore + SqliteVectorStore(JSON 向量/NumPy 点积)
```

前端与产物：
- **上传适配**：`apps/agent-server/document_upload.py` 负责类型/大小校验、临时文件清理并调用 ingestion 转换 Markdown。
- **Web 前端**：`apps/agent-server/webui/index.html` 负责页面结构，`knowledge_demo.css` 负责样式，`knowledge_demo.js` 负责笔记本创建、文件上传、知识库选择、示例问题和 SSE 聊天。
- **编译产物**：Jenkins/Linux 通过 `scripts/compile_extension_modules.py` 用 Cython 编成 `.so`；Windows 目标为 `.pyd`，独立 worker 的手动交付可由 `scripts/compile_service_executables.ps1` 生成 `bin/*.exe`；`scripts/package_release_artifacts.py` 生成发布元数据与注册表。

## 5. 关键设计决策

- **接口规范先行**：接口/类型先用 `specifications/` 定死，各模块按 `INTERFACE.md` 实现，减少联调返工。
- **源码隔离 + 二进制交付**：实现源码在 `modules-src/`，源码用于阅读、模块单测和构建；应用只消费 `artifacts/` 下编译扩展。当前只有 `verify_compiled_runtime.py` 运行验收入口，不支持应用源码模式。
- **接口为替换留出边界**：已经实现 DeepSeek/Mock 与 FastEmbed/hash 的选择；OpenAI provider、pgvector 和 Web MCP 接入仍需实现与测试，不能仅凭接口宣称已可切换。
- **演示数据边界**：CMRC2018 子集位于 `data/kb/cmrc2018-demo/`，通过正式知识库链路加载；它仅用于展示中文知识导入、检索、回答与引用，不承担向量模型评测。

## 6. 运行 / 测试

前提为依赖和当前平台编译工件齐备。新环境安装与离线 hash 配置见根 README；源码 editable 安装不能替代运行工件。下面的启动默认使用 FastEmbed，运行验收也会使用当前 embedding 配置。

```bash
.\.venv\Scripts\python.exe -m uvicorn --app-dir apps/agent-server server:app --port 8000
.\.venv\Scripts\python.exe scripts/verify_compiled_runtime.py
```

## 7. 原型边界

- Web 注册五个 RAG 工具与两个文件/保存工具，未注册 MCP 工具；LangChain/LangGraph/Hermes 未用于实现。
- Skill 是按匹配规则加载的完整 Markdown 指令，bug-triage/incident-analysis 文档写了业务步骤，不等于自动建单或持久工作流已实现。
- SSE 与 provider.stream 都在完整生成后返回一次结果；没有真正的 token streaming。
- retrieval_guard 最多提醒两次，之后可返回未检索答案。引用来源约束与回退顺序主要属于提示词策略，没有严格的输出验证闸门。
- RAG scope 是所选笔记本的过滤范围。服务无用户认证，客户端可提交 user_id，因此不能声称多租户权限隔离。SQLite 记忆不按 session_id 过滤，进程内聊天历史才使用用户/会话联合键。
- evaluate_qa 的词面重叠与长度分数属于启发式，不能证明回答正确率或真实性；当前没有真实模型的基准对比结论。
