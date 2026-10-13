# 企业研发知识与协作智能体系统（Dev Knowledge Agent）实施计划


## 当前生效：RAGnotebook 单进程、单数据库重构（2026-10-11）

本节由用户明确授权，优先于本文中旧的 Media 代理登录、多服务公开/私有部署、多数据库、20 次额度、manager 角色、自动迁移与独立管理员登录适配器方案。它们仅作历史记录，不再是本次实现依据。

### 目标与调用边界

浏览器只访问唯一后端应用 `RAGnotebook`。部署后只有一个 RAGnotebook 后端进程；`auth-facade`、`data-facade`、`rag-facade`、`agent-facade` 是同进程的二级业务模块，不是独立 HTTP 服务。调用链为 `浏览器 → RAGnotebook HTTP → 二级业务模块 → 数据/能力模块`。应用只能调用四个 facade 的公开 API；各 facade 可调用自己的一级模块及其他 facade 的公开 API。禁止 HTTP 路由直接调用一级模块、SQLite 类、向量类或文件存储实现。所有 RAG 功能必须归属具体二级业务模块。

### 业务模块归属与结果

- `RAGnotebook`（三层应用）：登录/注册、用户与笔记本页面、成员共享、上传/进度、问答/会话、管理员 Provider/Model 配置的 HTTP 和页面。它是唯一浏览器入口，不承担数据库、权限或 RAG 策略。
- `auth-facade`：账号注册/登录、活动状态鉴权、项目管理员用户管理、笔记本成员权限、每日额度；`auth-runtime` 只做密码哈希与进程内登录凭据验证。
- `data-facade`：唯一数据库入口；统一用户、笔记本、成员、文档分块和向量、会话历史、Agent 记忆/配置/技能/提示词及额度数据持久化。`storage` 与 `memory` 均归该业务模块，不由 Agent 间接借用。
- `rag-facade`：文档解析、切分、嵌入、写入/删除和检索；HTTP 上传经其公开的统一入库 API。
- `agent-facade`：问答执行和管理员 Provider/Model 目录、选择；密钥始终从服务器环境读取，不落数据库或前端。游客只能对当前活动 Provider 选择单次问答 Model，不会覆盖管理员设置。

### 首次数据库结构（首次创建后冻结）

只创建一个活动 SQLite 文件，schema 首次启用前完整确认；若已有表结构不匹配则启动失败，不自动 ALTER、不自动迁移。业务表固定为六张：

- `users(id, username, password_hash, is_admin, is_guest, is_active, quota_date, quota_used)`：本地登录账号、禁用状态和全站额度的分摊计数。
- `notebooks(id, owner_user_id, name, created_at)`：每个笔记本唯一所有者；所有者只对自己的笔记本具有 owner 权限，不是项目管理员。
- `notebook_members(notebook_id, user_id, role)`：角色仅 `editor`、`viewer`；所有者不重复登记为成员。
- `documents(id, document_id, notebook_id, file_name, chunk_index, content, embedding)`：文档块和向量共库保存。
- `conversations(id, user_id, notebook_id, title, messages, updated_at)`：只保存注册用户会话；游客问答不留历史。
- `agent_data(id, type, name, content, updated_at)`：Agent 记忆、技能、提示词、模型选择及其缓存配置。

不再创建独立 auth、memory、vector、state、quota 或 notebook 数据库文件；向量搜索直接读取同库文档向量。旧账号、旧笔记本、旧 ACL 不导入，旧数据不由新应用读取或修改。

### 重构01.1 发布规则（2026-10-13）

Jenkins 只构建 `master`。新版只发布统一 RAGnotebook 服务：先检查隔离候选容器，再切换 `ai-rag-agent-1`；成功后移除旧公开演示与双容器管理员进程。旧容器和进程不作为失败回滚目标，发布失败时停止新版服务并报告错误。旧数据卷保留，不导入新版单库，也不自动删除。测试仅覆盖现行统一服务发布、100 次全站额度及单库边界；旧版独立发布测试不再作为门禁。

### 账号、权限与额度

首次空库启动时，使用服务器一次性 bootstrap 环境配置创建一个项目管理员和固定游客账号；不提供默认密码。普通用户可以公开注册。管理员禁用账号后，后续每个请求都检查 `is_active` 并立即拒绝；项目管理员权限与 notebook owner 权限分开。登录凭据只存在后端内存，过期时间默认 12 小时；退出撤销当前凭据，服务重启清空全部登录状态，不建登录会话表。游客身份固定且所有游客共用；将游客加入笔记本仅允许 `viewer`，会明确告知所有游客都能查看该笔记本。分享界面先查有效用户，再由笔记本 owner 选人和角色；被禁用用户不能登录或访问共享内容。全站每天最多 100 次问答，注册用户、游客和管理员共用，北京时间零点重置，SQLite 事务原子预占；页面向游客显示共用剩余额度；游客问题和对话不入历史表。

### Web 接口与 Provider/Model

RAGnotebook 提供同源的注册/登录/退出/当前用户、管理员用户列表与启停、笔记本与成员查询/改权、文件上传/进度、问答/历史、管理员 Provider/Model 查询与选择、游客活动 Provider 模型目录与单次 Model 选择接口。所有私有端点在业务调用前先通过 `auth-facade` 鉴权；用户角色和 user_id 不接受前端自报。Provider/model 清单由后端基于已有 provider 能力与服务器凭据查询，管理员选择保存至 `agent_data`；切换立即影响新问答，不返回 API key。

### 服务器 Git、验收与发布

只在服务器上的独立 Git clone/worktree 开发。开始写代码前只读核实持久仓库路径、GitHub master SHA 和工作区状态；保留已有仓库/分支/脏文件，不在 Jenkins 临时目录编辑。完成后在主题分支提交并推送 GitHub。完成架构边界、六表单库、账号/禁用、共享和角色、游客历史隔离、100 次额度、入库检索与管理员模型选择验证；再把提交 SHA 和验证结果交构建发布职责执行 Linux 构建/发布，按其实际日志记录构建、部署和线上验收阶段。视频平台项目明确排除。

> 本文件是执行的唯一事实来源；主 Agent 与各 subagent 均以它为准。任何改动先回到这里。

## 目标

构建一个"会问答、会调工具、会走流程、记得住上下文"的企业研发助手，并以**接口规范先行 + 源码隔离 + 二进制交付**落地——集成/主 Agent 只拿到接口接口规范与编译后的二进制，看不到各模块实现源码，从而无法"顺手改"模块内部。

核心展示以公开 CMRC2018 中文语料贯穿“自动导入→检索→回答→引用”；同时提供类似 NotebookLM 的笔记本式知识库：用户可创建分类、上传文档并在每次对话中选择一个或多个知识库。工具调用、Skill、记忆和链路追踪由 Web 展示；MCP 是独立模块能力，当前 Web 的工具注册没有接入 MCP。

面试准备以“研发文档问答”为唯一主线。2026-10-08 用户明确面试准备时间为三天，理解基本原理但讲不清代码与设计选择。因此本轮优先校正说明、整理请求链路与可重复演示、练习设计取舍，不新增模块或更换运行框架。学习与演示入口见 `docs/INTERVIEW.md`。岗位要求中的 LangChain/LangGraph/Hermes 实践、持久工作流和真实效果评测仍需后续补齐，不能写成已完成。

## 仓库 / 工件布局（谁只能看到什么）

```
<workspace>/
  specifications/            # 接口规范层，唯一共享"源码"：core-specifications + INTERFACE.md + API_SCHEMA.json + test_specification.py
  modules-src/          # 一级模块 + agent-facade/rag-facade/data-facade；构建可见，运行不可见
    rag-core/  rag-tools/  memory/  llm-gateway/  tool-runtime/  mcp-gateway/  skill-runtime/
    agent-runtime/  observability/  evaluation/  ingestion/  mcp-servers/  storage/
  artifacts/            # 集成 Agent 只读：按 模块/版本/ 存放成品
    rag-core/1.2.0/rag_core.pyd + INTERFACE.md + API_SCHEMA.json + VERSION + CHANGELOG.md + test_specification.py + checksum.sha256
    ...
  registry.json         # 各模块版本 + checksum 索引，集成侧据此 pin 版本
  apps/                 # 集成 Agent 编写：agent-server(FastAPI) + web-ui + ingestion 调用 + MCP 调用
  data/kb/              # 项目知识库；内置公开中文演示语料与用户本地文档
```

- `specifications/`：接口与 schema（无实现），所有 subagent 与集成 Agent 可见、可校验。
- `modules-src/`：实现源码，按独立 Python 包和接口规范划分；当前发布单元是根目录 `ai-rag-platform` 仓库。历史上部分目录带有本地嵌套 Git 元数据，但没有远程仓库，不能把它们当作已发布的独立仓库。运行镜像不带源码，只消费编译产物。
- `artifacts/`：集成侧只从这里取版本化二进制 + 接口规范文档 + 接口规范测试。
- 已知限制：Codex 子 Agent 共享文件系统；开发阶段仍以接口规范和源码目录分工。Docker 在部署阶段隔离应用进程、依赖与持久化数据。

## 编译与交付形态

- **进程内模块**（`rag-core`、`rag-tools`、`memory`、`llm-gateway`、`tool-runtime`、`mcp-gateway`、`skill-runtime`、`agent-runtime`、`observability`、`evaluation`）：当前服务器流水线使用 **Cython** 编译成可 import 的扩展模块；Windows 目标为 `.pyd`，Linux 目标为 `.so`。本仓库没有 mypyc 编译路径。
- **独立 worker 交付**：`ingestion-worker` 的 Nuitka `.exe` 是 Windows 手动交付形式；当前 Linux Docker 服务直接调用编译后的 `ingestion` 模块。MCP 服务器通过编译扩展提供接口，Windows 独立执行形式不属于当前 Linux 部署步骤。
- **接口规范包**（`core-specifications`）：纯类型/接口规范（Pydantic + `RequestContext`），作为共享源码包，不编译隔离。
- 每个模块版本带 `VERSION`、`CHANGELOG.md`、`checksum.sha256` 与 `API_SCHEMA.json`；注册表 pin 已发布版本。模块快照 checksum 不含平台二进制，发布 ZIP 的逐文件清单与外层 SHA-256 覆盖实际交付内容。

## 关键接口与数据流

- **接口规范**：`RequestContext(trace_id, request_id, user_id, session_id)` 贯穿所有模块；各模块公开 facade 用类型化签名写死，供三个中间包组合一级模块；集成侧只直调 AgentService/RagService/DataService。
- **llm-gateway**：`LLMProvider.generate/stream/tool_call`；`DeepSeekProvider` 首个实现（`deepseek-chat` 函数调用，`deepseek-reasoner` 可选）；预留 OpenAI/Anthropic/Local。
- **rag-core**：`retrieve(query, scope) -> RetrievalResult`（embed→按知识库 scope 过滤→retrieve→context build→Citations），对 MCP、Skill 与前端无感知；部署默认使用 FastEmbed `BAAI/bge-small-zh-v1.5`，运行库或模型不可用时立即报错，仅显式设置 `RAG_EMBED=hash` 才启用无模型离线测试。RagService 将 embedding 标识存入现有 `agent_data`，模型改变时在启动阶段按数据库现有文本块重建向量；不新增表。查询改写和 rerank 保留为后续扩展点。
- **rag-tools**（原 `rag-skill`）：RAG 工具模块，向 LLM 公布五个知识库检索工具——向量语义 `search_knowledge_base`、融合 `hybrid_search_knowledge_base`、词面 `keyword_search_knowledge_base`、列目录 `list_knowledge_documents`、分页读原文 `read_knowledge_document`。每次调用只能访问当前对话选中的知识库，`read_knowledge_document` 拒绝范围外 `source_id`；返回结构化引用并记录带 `tool` 字段的 `rag` span。`read_knowledge_document` **必须分页**：默认只返回 20 块，返回值带 `total_chunks`/`truncated`/`next_offset`，一次调用不可能取回整篇长文档。检索算法在 `rag-core`，工具定义与执行在本模块，提示词策略在 `skills/rag-retrieval/SKILL.md`。
- **memory**：`SessionMemory`、`UserMemory` 两命名空间，`get/search/write/forget`；仅 memory 写库。
- **tool-runtime + mcp-gateway**：`@tool` 函数与 MCP 工具归一为同一 `Tool`；工具可选接收 `RequestContext` 与当前对话运行上下文；mcp-gateway 负责 discovery/connect/list/call/materialize。
- **skill-runtime**：`skills/*/SKILL.md`（frontmatter name/description + 指令 + 可选 `scripts/references/assets`），根据用户请求选择并加载完整技能内容，不得只把技能描述拼进提示词。
- **agent-runtime**（最薄）：理解请求→取记忆/对话历史→选并加载 Skill→调 LLM→按需执行 RAG/文件/入库工具→再调 LLM→写记忆→输出；工具循环默认最多 10 轮且可调高。提示词要求选中知识库时每个问题都先检索，未检索就收尾时追加 `RETRIEVAL_REQUIRED_MESSAGE`，最多 `MAX_RETRIEVAL_REMINDERS` 次并记录 `retrieval_guard` span；当前提醒耗尽可返回未检索答案，严格保证是待修复目标。提示词要求按 `search → hybrid → keyword → list_documents → read_document` 回退，执行器每轮只执行一次知识库检索。引用限于本轮工具返回的 source_id 是提示词约束，尚无严格输出校验。
- **observability**：跨模块结构化日志 + span 耗时，`GET /api/trace/{trace_id}` 看全链路；RAG 检索必须产生独立的 `rag` span，其元数据记录查询、知识库范围、命中数、来源、分数与短摘要；预留 Phoenix/OTel 适配器，v1 用内存 trace + 日志。
- **文档入库**：Web 接收 `.md`、`.txt`、`.docx`、`.pdf`，抽取正文后统一保存为 Markdown，再分块并加入所属笔记本的检索范围；原始上传文件与临时文件不进入仓库。
- **Agent 文件与对话入库**：工具只能在 `data/agent-files/` 创建新文件，不得覆盖仓库源码；用户要求保存对话时，工具将当前会话转为 Markdown，创建新笔记本并立即加入检索。
- **存储**：2026-10-09 重构后 Web 经 DataService 装配 SQLite `MemoryStore` 与 storage 的 `SqliteVectorStore`；向量以 JSON 存于 SQLite，搜索读出选定范围的向量后用 NumPy 点积排序，没有 FAISS/Chroma/pgvector 实现。`storage` 已纳入接口规范/名册，供 DataService 装配；统一后端和 pgvector 适配属于后续目标，不能称为已验证的无痛切换。

## 构建与集成工作流（主 agent 指挥，一模块一 subagent）

1. **接口规范先行**：协调 Agent 维护 `specifications/`（共享类型、各模块接口/schema 与签名闸门），并维护各模块包、`artifacts/` 与 `registry.json` 骨架；接口规范作为模块专职 Agent 的任务边界。
2. **模块开发（单仓库内按模块分工）**：每个专职 Agent 只改分配给自己的 `modules-src/<module>` 实现与测试；共享接口规范由协调 Agent 更新。模块目录是独立 Python 包与版本单元，不是独立 Git 仓库；根仓库是统一 Git 发布单元。
3. **服务器集成**：Jenkins 在 Linux Docker builder 中编译 Cython 扩展、打包版本化工件，运行模块单测、二进制签名接口规范、包内接口规范测试与应用端到端测试；失败时不部署。
4. **验收与部署**：服务器 Compose 用候选镜像健康检查并保留原镜像用于失败回滚；操作者从浏览器验收演示入口，不在本机编译 Linux 交付物。

## 测试计划与验收

- **单模块（源码仓库）**：pytest 单元测试（mock LLM/向量库/外部系统），编译前全绿。
- **接口规范测试**：严格模式仅从已注册 `artifacts/` 导入目标平台扩展，比较公开 facade 参数名与返回类型，并执行每个二进制包内随附的 `test_specification.py`。
- **集成/端到端**：本地起 agent-server + ingestion-worker(.exe) + mock MCP + SQLite，验证“CMRC2018 自动导入→选中知识库后每个问题至少检索一次→必要时按回退链换工具或改写查询→回答→引用”以及文件创建、对话入库、记忆和追踪链路；同时验证未选知识库时可直接回答，以及未检索就作答会被 `retrieval_guard` 拦截。每次检索可通过 trace 核对选中知识库和具体命中文档。
- **边界**：不比较中文向量模型，不把 CMRC2018 当作向量模型基准；只验证项目流程可运行。
- **验收目标**：所有模块版本化带 checksum、接口规范测试通过、源码模块单测与二进制集成运行可复现；运行镜像不包含模块实现源码。源码可供开发者学习和模块测试，应用启动仍只接受二进制。

## 假设与默认

- Python 3.11+；Windows 可编辑源码，Linux Docker 交付由服务器 Jenkins 完成。当前批量编译器为 Cython；构建阶段按目标平台生成 `.pyd` 或 `.so` 并写入 `artifacts/`，运行镜像只加载相同平台的扩展模块。Nuitka `.exe` 是 Windows worker 手动交付方式，不作为 Linux 容器前置条件。
- 除 DeepSeek 聊天 API 外无外部服务依赖；当前 Web 的记忆与向量由 DataService/本域 memory 与 storage 管理；直接 Python 启动时 embedding 默认为 FastEmbed `BAAI/bge-small-zh-v1.5`，Compose 配置默认显式使用 hash。
- `DEEPSEEK_API_KEY` 经 `.env` 注入，不入库；单用户单租户演示；可选简单 API key。Web 仅在 HTTPS 或本机页面允许单次页面会话内设置个人 DeepSeek 密钥，使用 POST 请求头覆盖该请求的默认 Provider；服务端校验请求 Origin，不持久化个人密钥，也不提供无鉴权的全局密钥修改接口。
- MCP connector（Git/Issue/工单）v1 用本地 mock，接口与真实连接器一致，便于日后插真。
- "SKILL" 采用 Agent Skills 的 SKILL.md 开放格式；前端为 agent-server 托管单页聊天（POST JSON）；旧 SSE 端点兼容服务器默认配置。

## Jenkins 与 Docker 部署（2026-09-28 验证状态）

1. Jenkins 在目标 Linux Docker 主机的 `media-workspace-agent` 上执行根仓库流水线。`Jenkinsfile` 通过 Docker builder 阶段运行模块单测、Linux Cython 编译、严格接口规范/应用端到端测试与打包；通过后归档 ZIP、逐文件清单和 SHA-256，再部署候选运行镜像。
2. 构建脚本按 Python 当前平台识别编译扩展的后缀，并把 `.pyd` / `.so` 放入相同模块版本的 `artifacts/`。注册表路径只使用 `/`，避免跨系统路径差异。
3. 运行镜像只包含 `specifications/`、`apps/`、`skills/`、只读演示语料、`artifacts/` 与注册表。`modules-src/` 和构建工具不进入运行镜像；模型缓存、数据库、用户笔记本与 Agent 文件通过 Docker volume 持久化。
4. Jenkins 以 Docker 健康检查确认候选服务可用；检查失败时恢复先前镜像，不删除命名数据卷。Compose 服务只绑定服务器 `127.0.0.1:18080`，没有通过该配置直接暴露公网；API 当前没有用户认证，新增公网反代前必须提供认证或只读演示边界。
5. 先前已验证记录：`ai-rag-platform #3` 成功，包含 73 项模块测试、2 项部署回滚测试、6 项严格接口规范测试、7 项应用端到端测试、Cython Linux 扩展运行验证与 129 文件 ZIP/manifest/SHA-256；当时 RAG 容器健康运行且只在服务器回环地址可达。本次加强后的签名/schema 比较和包内测试回放须由下一次 Jenkins 流水线重新验证。

## 仓库整理规则

- 源码仓库不保存本地编译结果、一次性演示脚本或一次性评测报告。为满足服务器持续交付，保存 `Dockerfile`、`compose.yaml` 与 `Jenkinsfile` 等可复现部署配置。
- `artifacts/` 只保留每个模块当前版本的发布接口规范；旧占位版本与本地二进制不保留。`reports/`、`bin/`、`build/` 均为可再生输出。
- 可执行脚本采用“动词 + 对象”命名，文件名必须直接说明职责；同一职责只保留一个入口。
- Web 演示语料必须实际存放在 `data/kb/cmrc2018-demo/`，并通过与本地文档一致的知识库加载链路进入检索；不保留独立的旁路数据集目录。
- Web 的问题提示从知识库清单读取精选问题，覆盖不同文档主题；完整问题集只作为可选数据，不直接挤满页面。
- 用户笔记本运行数据位于 `data/kb/user-notebooks/` 并被 Git 忽略；仓库只保留目录说明，确保初始版本纯净、未编译且不携带个人上传内容。

## 实现状态（2026-09-28）

> 以下为历史记录；面试和当前可用性以文末 2026-10-08 核对为准。历史流水线成功不等于当前本机产物或线上服务重新验收成功。

- 12 个已注册 Python 发布模块及接口规范、FastAPI 主进程、Web 聊天、RAG、工具、Skill、记忆与追踪代码均保留；另有未注册的 `storage` 源码目录不进入当前模块二进制闸门。
- Web 演示固定使用 `data/kb/cmrc2018-demo/` 中的 CMRC2018 dev 子集：24 篇文档、99 个问题；服务启动时导入知识库，页面展示导入状态与跨主题问题提示。
- Web 支持创建笔记本、上传 `.md/.txt/.docx/.pdf` 并统一转为 Markdown；聊天请求携带所选知识库标识，RAG 仅检索选中范围。
- RAG 检索作为独立 `rag` span 进入 trace，可查看实际查询、选中知识库及排名后的命中来源。
- RAG 默认使用 FastEmbed + `BAAI/bge-small-zh-v1.5`；不再吞掉依赖、下载或推理错误，hash 仅作为手动选择的离线开发后端。
- RAG 已改为 Agentic RAG：通过独立 `rag-tools` 模块注册为 LLM 工具；选择知识库后每个问题至少检索一次，未检索就想收尾会被 `retrieval_guard` 拦截，低质量结果按 `search → hybrid → keyword → list_documents → read_document` 逐级回退，每轮只执行一次检索。
- 移除三个无外部连接的模拟工具，改为七个真实工具：`rag-tools` 公布的五个知识库检索工具，加上受限文件创建与对话保存为新知识库。
- `.circleci`、旧虚构知识库、一次性演示脚本和一次性评测报告已移除。
- 脚本包含编译扩展、编译独立服务、打包发布接口规范、发布 ZIP 和验收二进制运行等明确职责；应用源码运行验收入口已移除。
- 服务器 Jenkins 已完成 Linux 二进制构建、发布包校验与 Compose 健康部署；本机不承担 Linux 编译。

## 三天面试准备与事实核对（2026-10-08）

第一阶段修改仅涉及实施计划、使用/架构说明和面试学习材料，不改变模块实现、接口规范、VERSION、checksum 或发布工件，尚未触发服务器部署。仓库规定的二进制边界保留；减少的是需要学习与展示的范围。随后用户补充了服务器、Jenkins 与主页演示要求，执行范围以下一节为准。

当前本机已核对：

- 显式 `RAG_EMBED=hash` 时 `scripts/verify_compiled_runtime.py` 输出 `COMPILED_AGENT_OK`，12 个注册模块由 `artifacts/` 的 Windows CPython 3.11 `.pyd` 加载。这仅证明离线二进制链路，不证明 BGE 或真实模型质量。
- 使用临时 STATE_DIR、hash embedding、空 DEEPSEEK_API_KEY 运行现有应用演示测试：7 项通过。
- 额外 API 上传复演在系统临时目录写文件时受到沙箱权限限制，申请提升权限未获用户批准，因此“创建笔记本→上传最新项目说明→问答→trace”的完整 API 复演未完成；不列为通过项。本轮没有绕过该拒绝或修改上传实现。
- `specifications/test_specification.py`：11 项通过、90 个 subtests 通过、3 个 subtests 失败。失败为本机二进制的 `LLMProvider.stream` 缺返回注解、`TraceStore.record(ev)` 与接口规范参数 `span` 不同、`evaluate_qa(ctx, qa)` 与接口规范参数 `qa_set` 不同。源码对应位置已是新签名；需由目标平台构建流程核实并重建产物，不能靠跳过测试宣布交付全绿。
- 当前应用 SSE 在 `runtime.run()` 完成后发送整条答案；模型网关的 `stream()` 也仅 yield 完整结果，不是逐 token 流。
- `retrieval_guard` 是最多两次提醒：本机二进制复现了模型始终不检索时仍返回答案。因此“每个问题至少检索一次”目前是目标策略，尚非严格保证；`retrieval_done` 在工具执行前设为 True，也没有成功结果闸门。回退顺序和引用可信性主要由提示词约束，不能声称已经硬性验证。
- 会话历史按 `(user_id, session_id)` 放在进程内；SQLite 记忆按 namespace/user_id 查找，没有 session_id 条件。笔记本检索范围过滤存在，但不能据此前端体验声称持久记忆已严格按会话隔离，更不是多租户鉴权。
- `evaluation` 中 faithfulness 为词面重叠启发式，answer_relevance 为答案长度启发式；LLM judge 异常也会回退为长度分数。当前无可信真实模型评测结论。
- 主 Web 未接入 MCP，也未依赖 LangChain/LangGraph/Hermes；Skill 是完整 Markdown 指令加载，并不执行持久工作流。API 尚无用户认证，不能称为生产平台。
- 注册表本机仍有反斜杠路径，加载器做兼容归一化；“注册表路径只使用 /”是交付目标，不是本机当前文件事实。本轮未核验服务器镜像、API key、BGE 缓存或线上状态。

准备顺序：第一天通过服务器公开演示讲通 `HTTP → AgentRuntime.run → ToolRegistry.execute → RagTools → rag_core → LLM` 并核对 trace；第二天记录固定问题的来源、模式、耗时和失败案例，能使用受保护私有工作区时再上传项目 README/架构说明到独立笔记本，区分 Mock 和真实模型；第三天完成 90 秒介绍、5 分钟演示、设计取舍追问和个人贡献核对。框架练习优先阅读官方 LangGraph workflow/agent 与 interrupt 示例，只有实际跑过、能解释状态与恢复边界后才写“实践过”。

三天之后的候选迭代按优先级：严格检索失败处理与会话记忆隔离；固定问题集和真实模型效果/延迟评测；一条 LangGraph 业务流程（明确状态、缺信息分支、持久 checkpoint、人工确认与幂等）；按业务需要接入只读 MCP。每项先更新本计划和接口规范，再做模块版本、单测、目标平台二进制与 checksum 更新。当前不把这些候选项记为实现承诺或已完成能力。

## 服务器与主页演示（2026-10-08 追加执行范围）

用户明确要求保留模块化、由 Jenkins 约束发布，并使用服务器在个人主页演示。因此继续推进服务器交付，不以本机文档或离线验证代替最终结果。执行开始时公网 `/projects/projects.html` 的研发文档问答没有演示入口，`/projects/apps/rag/` 返回 404；服务器连接由 build-delivery 单一负责人复用 SSH 长连接。最终上线记录见本节末尾。

实施边界：

- 先核对服务器最新 Git HEAD、镜像与 Jenkins 门禁，保留后续提交中的请求级模型设置；本机旧代码/二进制结果不推定为服务器结果。
- 业务模块继续只从注册工件加载，学习界面和 HTTP 适配放在 apps；主页只负责入口，部署负责人只改交付配置和执行流水线。若确需模块实现修复，则按现有接口规范、版本、CHANGELOG、二进制与 checksum 流程处理。
- 新公开演示使用独立容器/状态，不挂载原服务的私人笔记本、Agent 文件或密钥文件。公开范围只限 CMRC2018 内置资料、固定示例问题、只读知识库工具与本次调用 trace；关闭上传、建笔记本、创建文件、保存对话。2026-10-09 用户追加授权公开 Web 手动输入临时 key：仅 HTTPS/本机同源 POST 请求头使用，浏览器不持久保存，服务器运行环境无 key；携带 key 的请求绕过共享缓存，实际模型模式随响应显示。
- 演示页面用简短步骤串起“选问题→调用已有 Agent/RAG→查看来源→读 trace”，以实际响应呈现状态，不放虚构命中或进度。正常私有工作区仍可使用已有模型设置和上传能力。
- AI 仓库 Jenkins 必须完成模块单测、目标 Linux 编译、严格接口规范、应用集成、运行来源与发布包校验；公开演示边界需有有意义的集成检查。主页仓库 Jenkins 验证新链接/代理路径，并运行镜像和部署后 smoke。门禁失败不切换正式演示，不用改断言绕过失败。
- 既有 8088 主页路径可用；不改 DNS、云防火墙或 SSH 基础设施。公开 HTTPS 未验证时继续禁用 HTTP 密钥输入。上线完成以实际入口、API调用与 trace 检查为准；连接或门禁失败时如实保留待完成项。

本节方案已落实，实际服务器结果和最终模式见末尾交付记录。

落实约定见 `specifications/WEB_DEMO.md`：PUBLIC_DEMO 独立进程只加载内置 CMRC 资料、五个只读 RAG 工具和固定精选问题；POST /api/demo/chat 从服务端固定 scope/context，成功时核验实际 rag 来源，拒绝其他 API/扩权字段；增加一次并发、90 秒总超时、仅无 key 请求的 300 秒成功缓存。公开部署 DEMO_PROVIDER=mock 且 DEEPSEEK_API_KEY 为空；手动临时 key 按请求覆盖为 DeepSeek，公开页显示该次实际 provider，并从 trace 展示来源和阶段耗时。

初次核对服务器时，ai-rag-platform #7 在 HEAD 382aa9c 完成 73 项模块测试、2 项回滚测试、11 项严格接口规范、11 项应用测试和 12 个 Linux .so 来源验证；当时私有容器无模型密钥且使用 hash。项目本机 .env 已配置模型凭据，公开固定问题演示原拟经 build-delivery 安全传输为服务器仓库外的 0600 环境文件，Compose 只注入指定模型环境变量，不挂载凭据文件或私人数据。凭据传输仍未获明确授权，没有执行；使用模型凭据也不代表已测 BGE。

候选交付配置明确使用 `/home/ubuntu/.config/ai-rag/public-demo.env`。自动审批拒绝了现有密钥向服务器的传输，要求对这项凭据及目标服务器明确授权；当前未读出或传输密钥，授权问题已提交用户。在回复前只允许代码同步、Mock 检查及不启用部署的 Jenkins 构建，不将 DeepSeek 演示记为上线。

用户随后要求无人值守推进。为完成不依赖敏感凭据的服务器交付，允许先部署明确标注的 Mock 公开演示：发布流程显式选择 mock 并检查响应 provider 必须一致，使用不含密钥的环境文件；DeepSeek 仍需明确密钥授权且缺凭据拒绝启动。主页初始说明离线工具流程，只证明真实工具、检索与 trace 链路，不称为真实模型问答质量。已有 #8 构建继续完成，新增模式配置由后续 Jenkins 提交验证后部署；不改运行中的工作区、不跳过门禁。

服务器 #8 在 `4d89be5` 完成 73 项模块、4 项回滚、11 项严格接口规范、15 项应用检查和 12 个 Linux `.so` 来源验证，仅构建。#9 在 `f65e7ba` 完成 73/6/11/15 项检查及二进制来源验证，候选 Mock 问答/trace smoke 通过；正式部署失败，原因是 `sudo docker compose` 清除模式和环境文件路径变量，触发默认 DeepSeek 配置。没有发布主页卡片或启动公开服务，原私有服务保持正常。修复只向 Compose 显式转交这两个非敏感变量，并模拟 sudo 环境清理测试；由下一次 Jenkins 完整验证后重试，不记为上线成功。

### 公开交付与复验结果（2026-10-08 上线，2026-10-09 复验）

- AI Jenkins #10 在运行代码提交 `033328f11f41605d1cee907055b809d027f7043e` 上成功，显式参数为 `DeployDemo=false`、`DeployPublicDemo=true`、`PublicDemoProvider=mock`。73 项模块测试、6 项回滚测试（含 sudo 清理环境和模式/配置恢复）、11 项严格接口规范、15 项应用测试、12 个 Linux `.so` 来源检查全部通过；候选和切换后真实 HTTP 检索/trace smoke 均通过。
- 独立公开容器 `ai-rag-public-agent-1` 健康，绑定服务器回环地址 18106。仅挂载 `ai-rag-public_public-demo-state`，不含 `modules-src`，未配置模型密钥；12 个业务模块实际从 artifacts 的 `.so` 加载。原 18080 私有容器的 id/image 保持不变。
- 二进制 ZIP 的 SHA-256 为 `8130e56cec2c7fd4c5ff9acde4fc89b1df60ced87ba08e256bc6b51bdd5b9e44`，manifest 包含 12 个模块版本，包中无 `modules-src`。#9 与 #10 二进制包相同，因为修复只影响部署脚本和文档。
- 主页 Jenkins #24 在配套 portfolio 提交 `5081ac7071cb6ac1186d3955496d424feedf2122` 上以 `DEPLOY=true` 成功，保留其他应用和简历隐私检查，新增 RAG 代理 smoke 及服务器本地 HTTPS smoke 均通过。公网 HTTPS 可达性未作为通过项，也没有修改 DNS/云防火墙。
- 公网入口：[研发文档问答演示](http://43.153.176.182:8088/projects/apps/rag/)，主页项目卡片已提供链接。2026-10-08 浏览器实际点击卡片、加载八个问题并执行问答，看到了 Mock/hash 标签、实际来源、五个阶段和原请求缓存说明。
- 2026-10-08 与 2026-10-09 的公网 API 复验均通过：八个精选问题都有非空 CMRC 检索命中与实际 trace；重复调用复用原答案/trace 并标记 cache_hit；静态资源正常，私人/写 API 为 403，任意问题或扩权字段为 422，浏览器模型密钥头为 403，未知 trace 返回空数组。24 篇内置文档已导入。
- 当前为 **Mock + hash 的离线工具流程演示**，未完成真实 DeepSeek/BGE 回答质量评测。真实模型启用仍等待对现有凭据及目标服务器的明确授权。后续只读核查不重复部署；文档收尾不改变模块版本或已验证运行镜像。

### 2026-10-09 页面复查修正

公开页面的 Mock 工具 JSON 不再作为整段答案展开。问答区说明尚未生成自然语言答案，原始输出保留在折叠区；左右两栏继续显示实际检索来源与 trace。仅修改 Web 展示模块并更新资源版本，API、业务模块及凭据配置保持现有契约。经服务器 Jenkins 验证后再发布，未部署时不得记为线上修复。

### 2026-10-09 管理员笔记本与导入恢复方案

用户要求恢复原 NotebookLM 式创建笔记本和文档导入，只允许自己的管理员账号写入。公开 PUBLIC_DEMO 进程继续使用独立公开数据卷和现有只读边界；私有工作区通过 HTTPS 管理入口访问，身份必须复用已部署服务的真实管理员登录。公网反代验证会话及管理员身份后才允许转发，私有 RAG 还要核验服务器间认证证明和指定拥有者身份，不能信任浏览器自填的角色或用户头。所有私有页面、静态资源、笔记本内容、上传进度、聊天及 trace 都在该权限边界内；POST 导入/创建与可能调用写工具的聊天需要同源校验。凭据不进入前端、源码或公开数据卷。接口约定见 `specifications/WEB_ADMIN.md`。方案、代码和测试需经服务器 Docker/Jenkins 门禁以及真实登录后创建→导入→检索验收；未验证时不能记为上线完成。

已核对 Media 源码：其登录为 Spring/MySQL session，只有 ROLE_USER，没有全局管理员角色；RAG 通过已验证的不可变 owner UUID 与 username=owner 的组合授予专属管理权限。独立登录适配容器 18107 调用既有 Media 认证 API，Secure/HttpOnly/Strict 管理 cookie 仅在管理路径使用；guarded RAG 容器 18108 使用全新的私有笔记本/状态/文件卷。原私有 18080 和公开 18106 容器及数据卷保持独立，避免两个进程同时写同一 SQLite 或笔记本目录。初始管理区继续明确使用 Mock/hash；本次不传输或启用模型凭据。`DeployAdminWorkspace` 默认关闭，部署前要求服务器私有配置文件中已核对 owner UUID；候选容器先验证真实 Media 网络可达、认证拒绝、实际创建/导入/检索链路，切换后只读 smoke，失败恢复上一管理镜像/配置。部署脚本不删除任何持久管理数据卷，也不自动公开管理反代。

## 2026-10-09 三个中间模块重构（当前执行范围）

用户确认启用三个 subagent，无人值守实施。此前“面试优先不新增模块”的阶段限制由本次明确重构要求取代。先定义接口规范与测试，再由三个模块负责人分别实现。

- 接口目录改名为 specifications/，共享包 core_specifications，签名测试 test_specification.py，严格模式 SPEC_STRICT；所有构建和运行路径同步。
- 新增 agent-facade、rag-facade、data-facade 三个编译模块。服务组合根只导入三个中间包及共享规范/observability，不再构造一级模块。公共层为 core_specifications + observability；AGENT 叶子为 agent-runtime、llm-gateway、skill-runtime、tool-runtime、mcp-gateway、mcp-servers、evaluation；RAG 叶子为 rag-core、rag-tools、ingestion；数据库叶子为 memory、storage。
- VectorStore、MemoryStorePort、LLMProviderPort、TraceStorePort、StateStorePort、DataServicePort、RagServicePort 定义在共享规范。数据库只依赖本域实现；SQLite 向量存储迁至 storage。agent-runtime 通过共享 MemoryStorePort 接收记忆，不再 import memory。AGENT 中间包接收 DataServicePort/RagServicePort，禁止跨域导入具体叶子。
- 三包 API 的参数、返回类型、异常、生命周期和测试清单先写 specifications/DOMAIN_INTERFACES.md 与 API_SCHEMA.json；负责人不得自行更改共享签名。
- Web 静态资源独立放 apps/web/，不编译，仅调用 API；随发布包交付。HTTP 上传校验等适配仍在 apps/ragnotebook，文档转换调用 RAG 中间包。
- 测试覆盖一级模块、三个中间包、最终服务、编译产物行为及模块依赖规则。基线只用 data/kb/cmrc2018-demo/，检索回归跑全问题集，真实模型每次构建跑少量固定问题控制费用；不能用 Mock 代替真实模型验收。
- Jenkins 按准备环境、检查依赖、测试一级模块、测试中间模块、编译、验证编译产物、测试最终服务、实例文档与真实模型验收、打包归档的顺序显示步骤，并归档 JUnit 报告。API key 用 Jenkins secret text 凭据注入，禁止写入 Git、前端、镜像或报告；缺凭据则真实模型阶段失败。尚未连接或配置服务器 Jenkins。
- 本机可进行目标 Windows 编译与验证；Linux .so 仍须在 Linux Jenkins 节点生成。未完成的构建/远端结果据实记录，不把源码测试通过当作二进制交付完成。

### CMRC 重构前检索回归实测（2026-10-09）

明确使用 hash embedding，Top-5 期望来源命中：向量 95/99、词面 99/99、融合 99/99。每题期望来源为 manifest 对应文档，不评判模型质量。三域集成回归保持上述计数下限，失败报告文档名和题号；真模型验证另用固定精选问题。

### 本轮已完成与实际验收（2026-10-09）

三个 subagent 已分别交付 agent-facade、rag-facade、data-facade 0.1.0；共享接口迁移、跨域解耦、service组合根和 apps/web 拆分已落地。16个注册模块 Windows .pyd、版本/checksum 已更新。源码一级89、中间29、三域/分层7；二进制一级89、中间29、三域/分层7；严格规范12、服务15、WSL POSIX回滚6项通过；真实DeepSeek两题含实际来源、引用和答案核心内容断言通过。CMRC99题保持向量95/99、词面/融合99/99。发布包独立解压启动问答和静态资源通过。

Jenkins代码已改为分步测试、编译、每次真模型验收和归档报告。尚未运行远端流水线/配置其 rag-deepseek-api-key secret text，未重建Linux .so、未部署；本机给定key仅在授权验收进程内使用。详细结果、发布包SHA及限制见 docs/REFACTOR_VALIDATION.md。

### GitHub 合入与无 key 服务器交付（用户追加要求）

完整整合远端 23bb124 的 Knowledge Studio 页面、管理员身份验证及独立工作区，所有静态文件包括管理员登录迁至 apps/web。应用版本 0.4.1；公开页手动临时 key 使用同源 HTTPS 请求头，ContextVar 隔离与恢复，错误在记录 trace 前清理，有 key 请求不读取/写入共享缓存，无 key 默认 Mock。公开部署默认 mock，使用不含密钥的配置文件；构建阶段真实模型验收通过 Jenkins secret text，与运行容器分离。管理员验收问题明确要求查询文档以触发现有 Mock 工具策略，保留真实来源断言。用户已授权合入 GitHub 并通知指定主页/服务器 chat；Linux 流水线及上线结果待实际执行记录。

### 追加鉴权模块与管理员/游客权限（2026-10-10）

用户追加无人值守要求：独立 auth-runtime 编译模块（公共横切层）统一角色与权限；管理员通过已有 Media owner 登录及内部代理证明验证身份，可创建笔记本/导入；游客仅读取公开知识库和查询，不能读取私人管理员笔记本或执行写工具。不得以浏览器角色字段授予权限。共享 AuthPrincipal/AuthServicePort 与测试矩阵先定义在 specifications/AUTH_INTERFACES.md，再实现。公开 UI 增加管理员入口、公开文档列表与自由查询，明确游客身份；所有写 API 后端强制检查。私有管理区仍独立状态/卷并需要真实登录，公开用户不会自动获得私有导入数据。部署包含公共服务与已配置的管理员/login 服务，服务器模型 key 保持空，Web临时 key实测由用户完成。

### 鉴权业务从 agent-server 解耦（2026-10-10）

实施结果：管理员／游客权限决策与笔记本可见范围由独立编译业务模块 `auth-facade/AuthService` 提供；`auth-runtime/AuthRuntime` 仅保留游客身份创建、代理身份认证和管理员证明验证。`agent-server` 通过 AuthService 消费鉴权接口，不再承载策略实现。auth-facade 仅依赖共享类型和 auth-runtime，不依赖 Agent、RAG、Data 业务模块。接口详见 `specifications/AUTH_INTERFACES.md`。此处记录代码架构变更；尚不代表部署或线上验收。

### OpenRouter 默认模型与全站日额度（2026-10-10）

用户授权：使用提供的 OpenRouter 密钥作为 RAG 默认服务端凭据，只使用免费模型，Web 全站每天共 20 次问答。默认模型 `openrouter/free`，仅允许此路由或严格以 `:free` 结尾的模型，不配置付费回退。密钥只进入忽略且排除构建上下文的 `.env.openrouter` 或部署环境，不进入源码、网页、接口响应和日志。`LLM_PROVIDER=mock/deepseek` 保留明确选择的兼容模式。

额度策略放在 auth-facade 的 DailyQueryQuota，持久化通过共享 StateStorePort 注入，storage 提供事务原子递增；应用只适配 HTTP。按北京时间零点重置，固定服务端全站身份，客户端 user/session/IP 均不能扩大额度。验证合法请求、忙闲检查后，在模型执行前占用一次；缓存命中不消耗，模型执行失败或超时不退还。所有 Web 问答路径（含 SSE、临时密钥）使用同一额度；公开及私人容器需要共享独立 `WEB_QUOTA_STATE_DIR` 持久卷才能合并计数，不共享私人知识数据。

验收：并发不超过 20、重启不重置、跨日期重置、HTTP 超额 429、免费模型校验、密钥不输出、OpenRouter 配置元数据和网页剩余次数。生产凭据注入与发布由构建发布职责执行，代码构建不代表线上已切换。

实现与本机验收已完成，应用候选版本0.6.0，auth-facade0.2.0、storage0.3.0、共享包0.4.0。真实 OpenRouter 默认 RAG 问答200且有实际知识检索；免费调用费用0与源码/二进制/HTTP验收证据见 docs/OPENROUTER_RUNTIME.md。生产流水线模式、凭据环境文件和共享日额度卷仍待构建发布职责处理。

## 管理员部署验收修复（2026-10-10）

Jenkins17全部编译、源码/二进制、HTTP与真实模型门禁通过，公开服务发布成功；管理员候选被旧smoke的匿名笔记本列表403断言拦截。修正为游客200但仅CMRC，仍断言写入/私有范围403。恢复部署允许明确指定已通过上述门禁的不可变镜像SHA，避免仅修改部署检查脚本时重复编译；候选创建/导入/命中和回滚检查保持执行。随后发布主页并验证HTTPS owner登录权限及运行无key。

### 管理员与主页发布完成（2026-10-10）

修复提交 `851cf2c2caf058c83e9a5e6476d71dfecbb38392` 已合入 GitHub master。Jenkins `rag-admin-recovery-17 #2` 与 `project-index #28` 均 SUCCESS：恢复任务先验证 #17 全部门禁及不可变镜像，6项 Linux 部署回滚检查通过，候选环境完成创建笔记本、导入文档和真实来源检索，再发布正式管理员容器与主页反代。

最终 HTTPS 8443 入口已验证游客读取/自由查询、拒绝游客写入与私有访问、owner 实际登录/管理员权限/退出后拒绝访问。公开与管理员 agent 均为 0.5.0，17个模块从编译工件加载，运行镜像不含模块源码；公开 agent、管理员 agent、登录容器均健康且模型 key 为空。管理入口为 `https://portfolio.72945645.xyz:8443/projects/apps/rag/admin/login`，主页 0.5.0 卡片已发布。Web 手动临时 key 的真实调用由用户测试，未列为本轮线上通过项。详见 `docs/REFACTOR_VALIDATION.md`。

### 2 MB TXT 上传代理修复（2026-10-10）

用户上传银河笔记本 TXT 时收到 HTML，前端 JSON 解析失败。服务器日志确认 multipart 请求 2065625 字节在 Nginx `/_rag_owner_verify` 被默认 1 MB 限制返回 413，`auth_request` 转为 500；请求未进入 RAG 导入 API。修复主页仓库鉴权子请求限制，使其与管理员上传入口 20 MB 一致；内部验证仍不发送上传正文，登录接口 4 KB、公开接口 16 KB 及 owner 会话验证保持原边界。超出上传请求上限返回 JSON 413，避免同类 HTML 解析错误。新增真实 Nginx 大请求/匿名拒绝/超限回归，部署后验证 HTTPS 大请求到达 API，并在独立候选环境验证同等大小 TXT 转换、入库和检索；不改用户银河笔记本内容。

已完成：主页 PR #2 合入 main `5f7cc57`，Jenkins `project-index #29` SUCCESS。真实 Nginx 4项回归及其他项目路由 smoke 通过。正式 HTTPS owner 登录后 2065498字节请求到达上传 API，得到预期类型校验 JSON 415，无私有写入；独立候选 agent 对2065300字节 TXT 导入201、进度done、实际检索5个命中，用时1.7秒，随后销毁候选环境。修复属于共享 Nginx 中的 RAG 专用路由；三个二级模块未改动，不重复编译业务模块。

## 中文回答与笔记本成员权限（2026-10-11，任务 RAG-NOTEBOOK-20261011）

用户要求无人值守实施。首先明确业务边界，然后修改接口和实现，保留免费模型与全站每天20次规则。

| 业务模块 | 本次职责 | 服务/接口模块 |
| --- | --- | --- |
| agent-facade | 传递本次运行的写工具授权 | agent-runtime：默认简体中文，文档/工具/历史不能改变回答语言；无写权限时隐藏并拒绝非检索工具 |
| auth-facade | 笔记本成员、角色与访问策略 | auth-runtime：可信代理认证普通用户，签发绑定用户/角色的证明；共享 AuthServicePort 扩展 |
| data-facade | 提供持久状态接口 | 沿用 StateStorePort/storage 保存 ACL，无跨域具体实现依赖 |
| rag-facade | 在已经授权的笔记本范围检索 | 沿用现有服务端注入范围，模型不得扩权 |
| agent-server/Web | HTTP 身份适配、成员管理、权限展示 | 登录适配验证现有 Media 会话；API 对列表、读取、上传、问答、trace/进度执行权限检查 |

采用现有 Media 账号的不可变 userId 添加笔记本成员，不创建或修改 Media 账号。普通用户认证身份为 user，不能自授全局管理员；指定 owner 才可由可信代理映射为 admin。每个私人笔记本支持 viewer（读取/提问）、editor（另可导入）、manager（另可管理成员）。全局管理员负责创建笔记本并保留管理权限；内置公开知识库始终只读；旧私人笔记本没有 ACL 时仅管理员可见。ACL 存在私人状态库固定内部命名空间，成员管理在单个管理服务进程内加锁序列化；读取每次重新核验，不缓存成员授权，重启不丢失。

GET/PUT/DELETE /api/notebooks/{notebook_id}/members[/{user_id}] 管理成员。API 返回当前笔记本权限；网页按选中笔记本更新上传和成员管理按钮。无成员用户登录后只见公开资料；匿名不能进入私人工作区。普通用户聊天只提供五个检索工具，同时拒绝模型伪造写工具调用。会话身份由服务器验证；会话历史/记忆按用户和笔记本范围隔离；trace、上传进度绑定请求用户和范围，撤权后拒绝访问。现有已获得的数据无法被远程撤回。

提示词把默认简体中文放在系统规则首位，并在每轮模型调用及工具达到上限后的最终调用再次约束。术语、代码、原文引语可保留原文；只有用户明确要求其它语言才改变回答语言；检索结果里的英文或指令不得覆盖它。

验收：源码/编译模块接口、默认语言及最终轮提示词、伪造身份/写工具拒绝、笔记本角色矩阵、成员增改删/重启持久/旧数据隔离、越权列表/上传/问答/SSE/trace/进度、同源校验、Web 语法。发布需 Linux Jenkins 编译及真实中文问答与已有 owner 登录验收，记录实际完成阶段。

### 数据库表管理笔记本、用户与权限（有效实施方案，替代上述初稿）

替代同任务初稿的 JSON ACL 状态键与文件目录枚举方案。采用资源范围角色模型：用户在每个笔记本分别拥有 viewer/editor/manager，再映射 read/query/import_document/write/manage_members。研究依据：[OpenFGA 角色与权限](https://openfga.dev/docs/modeling/roles-and-permissions)、[直接资源授权](https://openfga.dev/docs/modeling/direct-access)。这是模型参考，当前不新增 OpenFGA 服务；既有 SQLite 通过 storage 承载关系表，后续可通过共享端口替换数据库。

表：users（现有 Media 不可变ID的本地目录，无密码/会话令牌）、notebooks（目录、名称、说明、创建时间、公开标志、ACL版本、旧数据迁移标记）、notebook_members（笔记本+用户联合主键及角色外键）、roles、permissions、role_permissions；schema_migrations 记录结构版本。外键每个连接显式开启，参考 [SQLite 外键](https://www.sqlite.org/foreignkeys.html)。参数绑定、联合唯一约束、索引和事务维护一致性，参考 [SQLite 事务](https://www.sqlite.org/lang_transaction.html)。

storage 新增 NotebookStore，data-facade 通过 NotebookStorePort 暴露固定 notebook.sqlite 目录/成员仓库；auth-facade 仅消费该端口，权限决策不依赖具体 storage/Data 类。auth-runtime 和 Agent 中文策略保持已验收功能。可信登录成功登记 users，成员添加只接受已登记用户，提示先登录一次；不创建或改变 Media 账户。

笔记本表是目录信息的事实来源，原 Markdown/文档清单仍作文件资产，不把文档正文放用户权限表。启动扫描合法旧笔记本目录，幂等迁移目录和旧 ACL；保留原文件。迁移与成员写入均在事务内执行，迁移标记避免重启后恢复已撤销的成员。成员变更先读取同一快照中的成员和 ACL版本，再做 expected_revision 比较更新；失败重新鉴权，避免跨连接/进程覆盖和撤权竞争。取消以全量 JSON 回写成员。

验收新增：关系表/主外键/索引、未登记用户拒绝、角色权限关联、多连接并发、版本冲突、事务失败不留半条数据、迁移幂等且旧撤权不复活、旧笔记本保留、真实进程重启。完成后更新正式接口、编译制品和发布说明；初稿 e7dc650 仅为开发分支，未上线。

权限矩阵及表字段正式依据：`docs/NOTEBOOK_PERMISSIONS.md`。按该文实现笔记本元数据更新、管理员归档/恢复和数据库成员管理；前述JSON初稿及其只含三角色操作的矩阵被该文替代。

## 2026-10-11 Provider与模型管理扩展设计

正式依据：[MODEL_CONFIGURATION.md](MODEL_CONFIGURATION.md)。维护provider/model目录表、启动及缓存刷新、管理员免费默认模型设置与本地额度重置审计；保持全站默认20次和免费限制。最新提问先形成设计；该扩展尚未实现，不将设计状态写成部署事实。笔记本关系表实现仍按NOTEBOOK_PERMISSIONS.md进行。

## 2026-10-11 变更按业务模块归结

用户要求所有变更归结具体业务模块，正式变更索引见[BUSINESS_CHANGE_MAP.md](BUSINESS_CHANGE_MAP.md)。笔记本目录业务方法先登记共享接口，再由data-facade提供；应用调用业务接口，storage只实现关系表。模型目录管理仍是已写设计、待实现，不归为现有服务成果。

模型环境配置策略也归agent-facade：先定义resolve_model_config与共享ModelConfiguration，提取既有配置选择及免费校验；model_config.py保留兼容入口，委托业务函数，不保存业务策略。

## RAGnotebook 0.9.0：来源管理与失败可诊断（2026-10-13）

用户授权从 master 独立分支实现本轮问题，允许在云工作区修改源码。基线为已部署 0.8.1 / 6af3fd8；保留其发布 tag v0.8.1。

- 应用：笔记本 owner 可确认后删除笔记本，清理来源、成员及关联会话；owner/editor 可删除来源，viewer/guest 不可。内置 CMRC 禁止删除。删除正在导入或问答使用的笔记本返回 409，避免导入复活来源。所有写入保持同源与服务端鉴权。
- data-facade：公开 delete_document(ctx, notebook_id, source_id)，按笔记本与来源精确删除全部分块；沿用 storage 的笔记本事务删除，无新增表或数据库。
- rag-facade：ingest / ingest_markdown 增加可选 progress 回调，报告解析、分块、32块分批向量进度、入库与完成；全量向量成功后才原子写入。rag-core 的已修复分批推理沿用。
- agent-facade：免费目录同时要求文本输入/输出与 tools 支持，不以目录数量作为可用性证明；不静默替换用户选定模型。llm-gateway 将限流、不可用、超时与畸形返回转为不含凭据的稳定错误。
- HTTP/Web：错误统一 JSON 并带 trace_id；单次问答总时限120秒，页面130秒取消等待，提供主动取消。上传弹窗内展示真实传输字节进度；后端解析/向量分块进度单独展示，不能把上传100%当作入库完成。长文档响应记录字节、字符、分块数量。
- 验收：删除 owner/editor/viewer/guest、跨笔记本及 CMRC 保护、删除后不再检索及重启；导入中进度可查询、失败原子性、真实上传《银河争霸战.txt》完整字数/分块证据；上游429/无效JSON/不支持工具返回结构化错误，超时取消释放问答锁；浏览器删除确认、可见上传进度和重试。源码、编译产物、接口签名与应用回归分别记录，不以 Mock 证明真实模型可用；至少10个具体模型的线上结果单独记录。

三级应用0.9.0；实际修改的二级模块为 data-facade、rag-facade、agent-facade，一级模块 llm-gateway；共享 specifications 随接口更新。auth-facade、storage、rag-core、agent-runtime 等标为沿用。服务器发布须在二进制验收通过后进行。

本轮二进制回归发现既有 compile_extension_modules 只交付包入口，遗漏 mcp_servers.github，导致 binary leaf 无法收集。构建入口同时编译并交付辅助可导入模块（不修改 MCP 实现），不复制源码或降低运行边界。
