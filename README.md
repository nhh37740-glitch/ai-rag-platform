# Dev Knowledge Agent

面向企业研发知识问答与协作的模块化 Agent，包含 RAG、MCP、Agent Skills、Function Calling、会话记忆和链路追踪。

文档入口：[`docs/PLAN.md`](docs/PLAN.md) 是唯一实施计划；[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) 解释模块关系；[`docs/MANUAL_COMPILATION.md`](docs/MANUAL_COMPILATION.md) 提供手动编译顺序。

## 目录职责

```text
contracts/                  共享类型、接口契约与契约测试
modules-src/                各独立模块的实现源码
artifacts/                  手动编译和发布后生成的版本化交付物
apps/agent-server/server.py FastAPI 服务与模块装配入口
apps/agent-server/document_upload.py 上传校验、临时文件清理与 Markdown 转换入口
apps/agent-server/webui/    笔记本管理、文件上传与中文知识问答页面
data/kb/                    内置中文语料与用户文档共用的项目知识库
data/agent-files/           Agent 只能在此创建的受限文本文件
skills/                     Agent Skills 定义
scripts/                    编译、打包和验收入口
registry.json               模块版本、校验和与发布状态
```

`scripts/` 只保留职责明确的入口：

- `compile_extension_modules.py`：编译进程内 Python 扩展模块。
- `compile_service_executables.ps1`：编译独立服务可执行文件。
- `package_release_artifacts.py`：生成发布契约、校验和与注册表。
- `verify_compiled_runtime.py`：验收二进制模式；业务模块必须全部来自 `artifacts/`，源码模式会被运行边界拒绝。

## 中文 RAG 演示

Web 启动时从 `data/kb/cmrc2018-demo/` 导入 CMRC2018 dev 子集，共 24 篇中文知识文档、99 个可用问题。页面还能创建独立笔记本，上传 `.md/.txt/.docx/.pdf` 并统一转成 Markdown；每次对话只检索勾选的知识库。内置语料只用于展示流程，不用于比较中文向量模型。

## Web 界面：笔记本即工作区

界面按"笔记本 = 独立工作区"组织：左栏列出全部笔记本与当前笔记本的来源，切换到某个笔记本就切换整个工作区——来源列表、对话记录、会话 id 都随之切换，互不干扰。

- 检索范围只包含当前笔记本，不存在"上一次还选中着"的残留状态。
- 每个笔记本一个会话（页面首次进入时生成），同一笔记本连续提问共享上下文，跨笔记本完全隔离。
- 上传只作用于当前笔记本；创建或导入完成后自动切到那个笔记本。
- 每条回答下方以小号等宽字体显示 trace id，可点击跳转到 `/api/trace/<id>`。

## 安装与启动

```powershell
uv venv .venv
uv pip install -e contracts -e modules-src/observability -e modules-src/memory -e modules-src/rag-core -e modules-src/rag-tools -e modules-src/llm-gateway -e modules-src/tool-runtime -e modules-src/skill-runtime -e modules-src/agent-runtime -e modules-src/evaluation -e modules-src/ingestion -e modules-src/mcp-gateway -e modules-src/mcp-servers -e modules-src/storage fastapi uvicorn python-multipart pypdf pytest

.\.venv\Scripts\python.exe -m uvicorn --app-dir apps/agent-server server:app --port 8000
```

浏览器打开 `http://127.0.0.1:8000/`。未配置 `DEEPSEEK_API_KEY` 时使用离线 Mock；在根目录 `.env` 配置该变量后使用 DeepSeek。

`rag_core` 会通过包依赖自动安装 FastEmbed，并在首次启动时加载 `.env` 中 `BGE_MODEL=BAAI/bge-small-zh-v1.5` 指定的中文向量模型。如果运行库或模型不可用，服务会直接报错；只有显式设置 `RAG_EMBED=hash` 才会启用无模型的离线向量。

Agent 实际获得七个真实工具：五个由 `rag-tools` 模块公布的知识库检索工具（`search_knowledge_base`、`hybrid_search_knowledge_base`、`keyword_search_knowledge_base`、`list_knowledge_documents`、`read_knowledge_document`），以及 `create_file` 和 `save_conversation_to_knowledge_base`。选择知识库后，每个问题都必须至少检索一次——模型若想不检索直接回答，会被打回重来并在 trace 里留下 `retrieval_guard` span；语义检索不理想时按提示词给出的顺序逐级回退到其他检索方式，每轮只执行一次知识库检索。工具循环默认最多 10 轮。

## 手动编译与验收

编译步骤见 [`docs/MANUAL_COMPILATION.md`](docs/MANUAL_COMPILATION.md)。整理后的命令为：

```powershell
.\.venv\Scripts\python.exe scripts/compile_extension_modules.py
.\scripts\compile_service_executables.ps1
.\.venv\Scripts\python.exe scripts/package_release_artifacts.py
.\.venv\Scripts\python.exe scripts/verify_compiled_runtime.py
.\.venv\Scripts\python.exe -m pytest contracts/test_contract.py
```

总体方案见 [`docs/PLAN.md`](docs/PLAN.md)，架构说明见 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)。

## Linux Docker 与 Jenkins 交付

根仓库是当前发布单元；`modules-src/` 中每个模块保留独立包、接口和版本，构建阶段用 Cython 编译为 Linux `.so`，运行镜像只包含 `artifacts/` 中的扩展、契约、应用、技能和演示语料。`runtime_boundary.py` 在启动时验证模块来源，缺少扩展时拒绝启动。

在有 Docker Compose 的 Linux 主机上，从仓库根目录运行：

```sh
docker compose --project-name ai-rag up -d --build
docker compose --project-name ai-rag ps
curl -f http://127.0.0.1:18080/api/demo
```

默认只监听服务器回环地址的 `18080` 端口，供同机反向代理使用。Compose 显式设置 `RAG_EMBED=hash`，这样无需下载模型即可启动演示；需要 BGE 语义向量时，配置 `RAG_EMBED=fastembed`，模型缓存使用独立 volume。数据库、向量索引、用户笔记本和 Agent 文件分别用 volume 持久化。`DEEPSEEK_API_KEY` 留空时继续使用 Mock；实际密钥仅通过 Jenkins 凭据或服务器环境变量注入。

`Jenkinsfile` 假设 Jenkins agent 运行在目标 Linux Docker 主机且有 Docker/Compose 权限。流水线依次执行模块单测、Linux 编译、严格契约测试、应用端到端测试、二进制运行边界验证；然后归档 `dist/ai-rag-platform-<version>-<platform>.zip`、SHA-256 与逐文件清单，再更新 Compose 服务并等待健康检查。ZIP 内不含 `modules-src/`。本仓库尚未配置具体 Jenkins job、服务器地址和凭据；可先在独立 Jenkins job 上运行此流水线，再将主页入口指向反向代理地址。
