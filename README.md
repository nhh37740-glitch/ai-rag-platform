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
- `verify_source_runtime.py` / `verify_compiled_runtime.py`：分别验收源码模式和二进制模式。

## 中文 RAG 演示

Web 启动时从 `data/kb/cmrc2018-demo/` 导入 CMRC2018 dev 子集，共 24 篇中文知识文档、99 个可用问题。页面还能创建独立笔记本，上传 `.md/.txt/.docx/.pdf` 并统一转成 Markdown；每次对话只检索勾选的知识库。内置语料只用于展示流程，不用于比较中文向量模型。

## 安装与启动

```powershell
uv venv .venv
uv pip install -e contracts -e modules-src/observability -e modules-src/memory -e modules-src/rag-core -e modules-src/rag-skill -e modules-src/llm-gateway -e modules-src/tool-runtime -e modules-src/skill-runtime -e modules-src/agent-runtime -e modules-src/evaluation -e modules-src/ingestion -e modules-src/mcp-gateway -e modules-src/mcp-servers -e modules-src/storage fastapi uvicorn python-multipart pypdf pytest

.\.venv\Scripts\python.exe -m uvicorn --app-dir apps/agent-server server:app --port 8000
```

浏览器打开 `http://127.0.0.1:8000/`。未配置 `DEEPSEEK_API_KEY` 时使用离线 Mock；在根目录 `.env` 配置该变量后使用 DeepSeek。

`rag_core` 会通过包依赖自动安装 FastEmbed，并在首次启动时加载 `.env` 中 `BGE_MODEL=BAAI/bge-small-zh-v1.5` 指定的中文向量模型。如果运行库或模型不可用，服务会直接报错；只有显式设置 `RAG_EMBED=hash` 才会启用无模型的离线向量。

Agent 实际获得三个真实工具：`search_knowledge_base`、`create_file` 和 `save_conversation_to_knowledge_base`。RAG 由独立 `rag-skill` 模块执行；选择知识库后，事实和定义类问题会强烈约束为先检索核实，低质量结果需要改写查询后再次检索。工具循环默认最多 10 轮。

## 手动编译与验收

编译步骤见 [`docs/MANUAL_COMPILATION.md`](docs/MANUAL_COMPILATION.md)。整理后的命令为：

```powershell
.\.venv\Scripts\python.exe scripts/compile_extension_modules.py
.\scripts\compile_service_executables.ps1
.\.venv\Scripts\python.exe scripts/package_release_artifacts.py
.\.venv\Scripts\python.exe scripts/verify_source_runtime.py
.\.venv\Scripts\python.exe scripts/verify_compiled_runtime.py
.\.venv\Scripts\python.exe -m pytest contracts/test_contract.py
```

总体方案见 [`docs/PLAN.md`](docs/PLAN.md)，架构说明见 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)。
