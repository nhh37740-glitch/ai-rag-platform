# Dev Knowledge Agent

面向企业研发知识问答与协作的模块化 Agent，包含 RAG、MCP、Agent Skills、Function Calling、会话记忆和链路追踪。

文档入口：[`docs/PLAN.md`](docs/PLAN.md) 是唯一实施计划；[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) 解释模块关系；[`docs/MANUAL_COMPILATION.md`](docs/MANUAL_COMPILATION.md) 提供手动编译顺序。

## 目录职责

```text
contracts/                  共享类型、接口契约与契约测试
modules-src/                各独立模块的实现源码
artifacts/                  手动编译和发布后生成的版本化交付物
apps/agent-server/server.py FastAPI 服务与模块装配入口
apps/agent-server/webui/    中文知识库演示页面、样式和交互脚本
data/kb/                    内置中文语料与用户文档共用的项目知识库
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

Web 启动时从 `data/kb/cmrc2018-demo/` 导入 CMRC2018 dev 子集，共 24 篇中文知识文档、99 个可用问题。页面展示8个跨主题问题提示；语料只用于展示“导入→检索→回答→引用”流程，不用于比较中文向量模型。

## 安装与启动

```powershell
uv venv .venv
uv pip install -e contracts -e modules-src/observability -e modules-src/memory -e modules-src/rag-core -e modules-src/llm-gateway -e modules-src/tool-runtime -e modules-src/skill-runtime -e modules-src/agent-runtime -e modules-src/evaluation -e modules-src/ingestion -e modules-src/mcp-gateway -e modules-src/mcp-servers -e modules-src/storage fastapi uvicorn pytest python-docx

.\.venv\Scripts\python.exe -m uvicorn --app-dir apps/agent-server server:app --port 8000
```

浏览器打开 `http://127.0.0.1:8000/`。未配置 `DEEPSEEK_API_KEY` 时使用离线 Mock；在根目录 `.env` 配置该变量后使用 DeepSeek。

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
