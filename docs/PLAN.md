# 企业研发知识与协作智能体系统（Dev Knowledge Agent）实施计划

> 本文件是执行的唯一事实来源；主 Agent 与各 subagent 均以它为准。任何改动先回到这里。

## 目标

构建一个"会问答、会调工具、会走流程、记得住上下文"的企业研发助手，并以**契约先行 + 源码隔离 + 二进制交付**落地——集成/主 Agent 只拿到接口契约与编译后的二进制，看不到各模块实现源码，从而无法"顺手改"模块内部。

核心展示以公开 CMRC2018 中文语料贯穿“自动导入→检索→回答→引用”；同时提供类似 NotebookLM 的笔记本式知识库：用户可创建分类、上传文档并在每次对话中选择一个或多个知识库。工具调用、MCP、Skill、用户/会话记忆和链路追踪作为独立能力入口展示。

## 仓库 / 工件布局（谁只能看到什么）

```
<workspace>/
  contracts/            # 契约层，唯一共享"源码"：core-contracts + INTERFACE.md + API_SCHEMA.json + test_contract.py
  modules-src/          # 各模块源码包；Docker 构建阶段可见，运行阶段不可见
    rag-core/  rag-tools/  memory/  llm-gateway/  tool-runtime/  mcp-gateway/  skill-runtime/
    agent-runtime/  observability/  evaluation/  ingestion/  mcp-servers/  storage/
  artifacts/            # 集成 Agent 只读：按 模块/版本/ 存放成品
    rag-core/1.2.0/rag_core.pyd + INTERFACE.md + API_SCHEMA.json + VERSION + CHANGELOG.md + test_contract.py + checksum.sha256
    ...
  registry.json         # 各模块版本 + checksum 索引，集成侧据此 pin 版本
  apps/                 # 集成 Agent 编写：agent-server(FastAPI) + web-ui + ingestion 调用 + MCP 调用
  data/kb/              # 项目知识库；内置公开中文演示语料与用户本地文档
```

- `contracts/`：接口与 schema（无实现），所有 subagent 与集成 Agent 可见、可校验。
- `modules-src/`：实现源码，按独立 Python 包和契约划分；当前发布单元是根目录 `ai-rag-platform` 仓库。历史上部分目录带有本地嵌套 Git 元数据，但没有远程仓库，不能把它们当作已发布的独立仓库。运行镜像不带源码，只消费编译产物。
- `artifacts/`：集成侧只从这里取版本化二进制 + 契约文档 + 契约测试。
- 已知限制：Codex 子 Agent 共享文件系统；开发阶段仍以契约和源码目录分工。Docker 在部署阶段隔离应用进程、依赖与持久化数据。

## 编译与交付形态

- **进程内模块**（`rag-core`、`rag-tools`、`memory`、`llm-gateway`、`tool-runtime`、`mcp-gateway`、`skill-runtime`、`agent-runtime`、`observability`、`evaluation`）：当前服务器流水线使用 **Cython** 编译成可 import 的扩展模块；Windows 目标为 `.pyd`，Linux 目标为 `.so`。本仓库没有 mypyc 编译路径。
- **独立 worker 交付**：`ingestion-worker` 的 Nuitka `.exe` 是 Windows 手动交付形式；当前 Linux Docker 服务直接调用编译后的 `ingestion` 模块。MCP 服务器通过编译扩展提供接口，Windows 独立执行形式不属于当前 Linux 部署步骤。
- **契约包**（`core-contracts`）：纯类型/契约（Pydantic + `RequestContext`），作为共享源码包，不编译隔离。
- 每个模块版本带 `VERSION`、`CHANGELOG.md`、`checksum.sha256` 与 `API_SCHEMA.json`；注册表 pin 已发布版本。模块快照 checksum 不含平台二进制，发布 ZIP 的逐文件清单与外层 SHA-256 覆盖实际交付内容。

## 关键接口与数据流

- **契约**：`RequestContext(trace_id, request_id, user_id, session_id)` 贯穿所有模块；各模块公开 facade 用类型化签名写死，供集成侧 `from rag_core import RagClient` 直调。
- **llm-gateway**：`LLMProvider.generate/stream/tool_call`；`DeepSeekProvider` 首个实现（`deepseek-chat` 函数调用，`deepseek-reasoner` 可选）；预留 OpenAI/Anthropic/Local。
- **rag-core**：`retrieve(query, scope) -> RetrievalResult`（embed→按知识库 scope 过滤→retrieve→context build→Citations），对 MCP、Skill 与前端无感知；默认必须通过 FastEmbed 运行 `BAAI/bge-small-zh-v1.5`，运行库或模型不可用时立即报错，仅显式设置 `RAG_EMBED=hash` 才启用无模型的离线回退；查询改写和 rerank 保留为后续扩展点。
- **rag-tools**（原 `rag-skill`）：RAG 工具模块，向 LLM 公布五个知识库检索工具——向量语义 `search_knowledge_base`、融合 `hybrid_search_knowledge_base`、词面 `keyword_search_knowledge_base`、列目录 `list_knowledge_documents`、分页读原文 `read_knowledge_document`。每次调用只能访问当前对话选中的知识库，`read_knowledge_document` 拒绝范围外 `source_id`；返回结构化引用并记录带 `tool` 字段的 `rag` span。`read_knowledge_document` **必须分页**：默认只返回 20 块，返回值带 `total_chunks`/`truncated`/`next_offset`，一次调用不可能取回整篇长文档。检索算法在 `rag-core`，工具定义与执行在本模块，提示词策略在 `skills/rag-retrieval/SKILL.md`。
- **memory**：`SessionMemory`、`UserMemory` 两命名空间，`get/search/write/forget`；仅 memory 写库。
- **tool-runtime + mcp-gateway**：`@tool` 函数与 MCP 工具归一为同一 `Tool`；工具可选接收 `RequestContext` 与当前对话运行上下文；mcp-gateway 负责 discovery/connect/list/call/materialize。
- **skill-runtime**：`skills/*/SKILL.md`（frontmatter name/description + 指令 + 可选 `scripts/references/assets`），根据用户请求选择并加载完整技能内容，不得只把技能描述拼进提示词。
- **agent-runtime**（最薄）：理解请求→取记忆/对话历史→选并加载 Skill→调 LLM→按需执行 RAG/文件/入库工具→再调 LLM→写记忆→输出；工具循环默认最多 10 轮且可调高。只要当前对话选中了知识库，**每个问题都必须至少检索一次**，闲聊、翻译、计算、创作、玩笑、商品询价也不例外；模型若想不检索直接收尾，`run()` 会把它打回并追加 `RETRIEVAL_REQUIRED_MESSAGE`，最多 `MAX_RETRIEVAL_REMINDERS` 次，每次拦截记一条 `retrieval_guard` span。结果不理想时按 `search → hybrid → keyword → list_documents → read_document` 逐级回退，且每轮只执行一次知识库检索，先读结果再决定下一步。只有未选择知识库时才允许直接回答。引用只能来自本轮工具返回的 `source_id`，历史对话里的引用不得复用。
- **observability**：跨模块结构化日志 + span 耗时，`GET /api/trace/{trace_id}` 看全链路；RAG 检索必须产生独立的 `rag` span，其元数据记录查询、知识库范围、命中数、来源、分数与短摘要；预留 Phoenix/OTel 适配器，v1 用内存 trace + 日志。
- **文档入库**：Web 接收 `.md`、`.txt`、`.docx`、`.pdf`，抽取正文后统一保存为 Markdown，再分块并加入所属笔记本的检索范围；原始上传文件与临时文件不进入仓库。
- **Agent 文件与对话入库**：工具只能在 `data/agent-files/` 创建新文件，不得覆盖仓库源码；用户要求保存对话时，工具将当前会话转为 Markdown，创建新笔记本并立即加入检索。
- **存储**：`storage` 接口统一用户/会话/记忆/文档元数据/向量/评测结果；默认 **SQLite 元数据 + 本地向量库（FAISS/Chroma）**，接口与 PostgreSQL+pgvector 同构，可无痛切换；本地 BGE（默认 `bge-small-zh`）。

## 构建与集成工作流（主 agent 指挥，一模块一 subagent）

1. **契约先行**：协调 Agent 维护 `contracts/`（共享类型、各模块接口/schema 与签名闸门），并维护各模块包、`artifacts/` 与 `registry.json` 骨架；契约作为模块专职 Agent 的任务边界。
2. **模块开发（单仓库内按模块分工）**：每个专职 Agent 只改分配给自己的 `modules-src/<module>` 实现与测试；共享契约由协调 Agent 更新。模块目录是独立 Python 包与版本单元，不是独立 Git 仓库；根仓库是统一 Git 发布单元。
3. **服务器集成**：Jenkins 在 Linux Docker builder 中编译 Cython 扩展、打包版本化工件，运行模块单测、二进制签名契约、包内契约测试与应用端到端测试；失败时不部署。
4. **验收与部署**：服务器 Compose 用候选镜像健康检查并保留原镜像用于失败回滚；操作者从浏览器验收演示入口，不在本机编译 Linux 交付物。

## 测试计划与验收

- **单模块（源码仓库）**：pytest 单元测试（mock LLM/向量库/外部系统），编译前全绿。
- **契约测试**：严格模式仅从已注册 `artifacts/` 导入目标平台扩展，比较公开 facade 参数名与返回类型，并执行每个二进制包内随附的 `test_contract.py`。
- **集成/端到端**：本地起 agent-server + ingestion-worker(.exe) + mock MCP + SQLite，验证“CMRC2018 自动导入→选中知识库后每个问题至少检索一次→必要时按回退链换工具或改写查询→回答→引用”以及文件创建、对话入库、记忆和追踪链路；同时验证未选知识库时可直接回答，以及未检索就作答会被 `retrieval_guard` 拦截。每次检索可通过 trace 核对选中知识库和具体命中文档。
- **边界**：不比较中文向量模型，不把 CMRC2018 当作向量模型基准；只验证项目流程可运行。
- **验收**：所有模块版本化带 checksum、契约测试通过、源码与二进制两种运行模式可复现；集成侧工作区无任何模块实现源码。

## 假设与默认

- Python 3.11+；Windows 可编辑源码，Linux Docker 交付由服务器 Jenkins 完成。当前批量编译器为 Cython；构建阶段按目标平台生成 `.pyd` 或 `.so` 并写入 `artifacts/`，运行镜像只加载相同平台的扩展模块。Nuitka `.exe` 是 Windows worker 手动交付方式，不作为 Linux 容器前置条件。
- 除 DeepSeek 聊天 API 外无外部服务依赖；存储默认 SQLite + 本地向量库，走 `storage` 接口以便切 pgvector；默认由 FastEmbed 在本地运行 `BAAI/bge-small-zh-v1.5`。
- `DEEPSEEK_API_KEY` 经 `.env` 注入，不入库；单用户单租户演示；可选简单 API key。Web 仅在 HTTPS 或本机页面允许单次页面会话内设置个人 DeepSeek 密钥，使用 POST 请求头覆盖该请求的默认 Provider；服务端校验请求 Origin，不持久化个人密钥，也不提供无鉴权的全局密钥修改接口。
- MCP connector（Git/Issue/工单）v1 用本地 mock，接口与真实连接器一致，便于日后插真。
- "SKILL" 采用 Agent Skills 的 SKILL.md 开放格式；前端为 agent-server 托管单页聊天（POST JSON）；旧 SSE 端点兼容服务器默认配置。

## Jenkins 与 Docker 部署（2026-09-28 验证状态）

1. Jenkins 在目标 Linux Docker 主机的 `media-workspace-agent` 上执行根仓库流水线。`Jenkinsfile` 通过 Docker builder 阶段运行模块单测、Linux Cython 编译、严格契约/应用端到端测试与打包；通过后归档 ZIP、逐文件清单和 SHA-256，再部署候选运行镜像。
2. 构建脚本按 Python 当前平台识别编译扩展的后缀，并把 `.pyd` / `.so` 放入相同模块版本的 `artifacts/`。注册表路径只使用 `/`，避免跨系统路径差异。
3. 运行镜像只包含 `contracts/`、`apps/`、`skills/`、只读演示语料、`artifacts/` 与注册表。`modules-src/` 和构建工具不进入运行镜像；模型缓存、数据库、用户笔记本与 Agent 文件通过 Docker volume 持久化。
4. Jenkins 以 Docker 健康检查确认候选服务可用；检查失败时恢复先前镜像，不删除命名数据卷。Compose 服务只绑定服务器 `127.0.0.1:18080`，没有通过该配置直接暴露公网；API 当前没有用户认证，新增公网反代前必须提供认证或只读演示边界。
5. 先前已验证记录：`ai-rag-platform #3` 成功，包含 73 项模块测试、2 项部署回滚测试、6 项严格契约测试、7 项应用端到端测试、Cython Linux 扩展运行验证与 129 文件 ZIP/manifest/SHA-256；当时 RAG 容器健康运行且只在服务器回环地址可达。本次加强后的签名/schema 比较和包内测试回放须由下一次 Jenkins 流水线重新验证。

## 仓库整理规则

- 源码仓库不保存本地编译结果、一次性演示脚本或一次性评测报告。为满足服务器持续交付，保存 `Dockerfile`、`compose.yaml` 与 `Jenkinsfile` 等可复现部署配置。
- `artifacts/` 只保留每个模块当前版本的发布契约；旧占位版本与本地二进制不保留。`reports/`、`bin/`、`build/` 均为可再生输出。
- 可执行脚本采用“动词 + 对象”命名，文件名必须直接说明职责；同一职责只保留一个入口。
- Web 演示语料必须实际存放在 `data/kb/cmrc2018-demo/`，并通过与本地文档一致的知识库加载链路进入检索；不保留独立的旁路数据集目录。
- Web 的问题提示从知识库清单读取精选问题，覆盖不同文档主题；完整问题集只作为可选数据，不直接挤满页面。
- 用户笔记本运行数据位于 `data/kb/user-notebooks/` 并被 Git 忽略；仓库只保留目录说明，确保初始版本纯净、未编译且不携带个人上传内容。

## 实现状态（2026-09-28）

- 12 个已注册 Python 发布模块及契约、FastAPI 主进程、Web 聊天、RAG、工具、Skill、记忆与追踪代码均保留；另有未注册的 `storage` 源码目录不进入当前模块二进制闸门。
- Web 演示固定使用 `data/kb/cmrc2018-demo/` 中的 CMRC2018 dev 子集：24 篇文档、99 个问题；服务启动时导入知识库，页面展示导入状态与跨主题问题提示。
- Web 支持创建笔记本、上传 `.md/.txt/.docx/.pdf` 并统一转为 Markdown；聊天请求携带所选知识库标识，RAG 仅检索选中范围。
- RAG 检索作为独立 `rag` span 进入 trace，可查看实际查询、选中知识库及排名后的命中来源。
- RAG 默认使用 FastEmbed + `BAAI/bge-small-zh-v1.5`；不再吞掉依赖、下载或推理错误，hash 仅作为手动选择的离线开发后端。
- RAG 已改为 Agentic RAG：通过独立 `rag-tools` 模块注册为 LLM 工具；选择知识库后每个问题至少检索一次，未检索就想收尾会被 `retrieval_guard` 拦截，低质量结果按 `search → hybrid → keyword → list_documents → read_document` 逐级回退，每轮只执行一次检索。
- 移除三个无外部连接的模拟工具，改为七个真实工具：`rag-tools` 公布的五个知识库检索工具，加上受限文件创建与对话保存为新知识库。
- `.circleci`、旧虚构知识库、一次性演示脚本和一次性评测报告已移除。
- 脚本已收敛为编译扩展、编译独立服务、打包发布、验收源码运行和验收二进制运行五项明确职责。
- 服务器 Jenkins 已完成 Linux 二进制构建、发布包校验与 Compose 健康部署；本机不承担 Linux 编译。
