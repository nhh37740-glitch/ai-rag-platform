# 研发文档问答（Dev Knowledge Agent）

上传研发文档，在所选笔记本内查资料、返回来源，并通过 trace 查看检索与工具调用过程。当前 Web 使用自写 Python Agent 循环，集成 RAG、Agent Skills、Function Calling、记忆和链路追踪；MCP 是独立模块，尚未接入该 Web。

准备面试先读 [`docs/INTERVIEW.md`](docs/INTERVIEW.md)：一条请求链路、三天练习安排、演示步骤及能力边界。当前没有 LangChain/LangGraph/Hermes 实践实现，也没有可信的回答质量提升数据。2026-10-08 本机二进制链路和 7 项应用演示测试通过，契约检查有 3 处产物签名不一致，详情见 [`docs/PLAN.md`](docs/PLAN.md#三天面试准备与事实核对2026-10-08)。

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
- 页面为每个笔记本生成独立会话 id，同一笔记本连续提问共享聊天历史；后端持久记忆尚未按 session_id 过滤，因此不能保证全部记忆跨笔记本隔离。
- 上传只作用于当前笔记本；创建或导入完成后自动切到那个笔记本。
- 每条回答下方以小号等宽字体显示 trace id，可点击跳转到 `/api/trace/<id>`。

## 安装与启动

```powershell
uv venv .venv
uv pip install --python .venv/Scripts/python.exe -r requirements-runtime.txt

# 前提：artifacts 中已有与当前 Python ABI/平台匹配的全部 published 扩展。
# 未交付二进制时先走下方 Linux Docker 构建或构建机流程，不能直接用源码启动。
.\.venv\Scripts\python.exe scripts/verify_compiled_runtime.py
.\.venv\Scripts\python.exe -m uvicorn --app-dir apps/agent-server server:app --port 8000
```

浏览器打开 `http://127.0.0.1:8000/`。当前本机工件为 Windows CPython 3.11 扩展，创建新环境时应使用匹配的解释器。编译工件被 Git 忽略，clone 仓库不会自动获得它们；安装 editable 业务源码也无法替代工件。源码安装仅用于模块单测和构建阶段，见 `Dockerfile`。

未配置 `DEEPSEEK_API_KEY` 时使用离线 Mock；在根目录 `.env` 配置该变量后使用 DeepSeek。Mock 通过关键词选工具，可能原样返回工具 JSON 或固定文本，只可证明链路，不可当成真实问答效果。无需模型的离线演练要显式设置 `$env:RAG_EMBED='hash'`；默认 FastEmbed 可能下载模型。

页面右上角「DeepSeek 设置」可为当前页面设置、替换或移除个人密钥。仅 HTTPS 或本机页面允许输入个人密钥；服务端也会拒绝来自公网 HTTP 页面携带密钥的请求。密钥只保留在页面内存中，通过同源 `POST /api/chat` 的请求头传递，刷新后清除；移除后恢复服务器配置或离线 Mock。服务端不保存浏览器密钥，`GET /api/llm/config` 只返回服务器是否已配置的布尔值和模型名。旧 `GET /api/chat/stream` 继续使用服务器配置。

`rag_core` 会通过包依赖自动安装 FastEmbed，并在首次启动时加载 `.env` 中 `BGE_MODEL=BAAI/bge-small-zh-v1.5` 指定的中文向量模型。如果运行库或模型不可用，服务会直接报错；只有显式设置 `RAG_EMBED=hash` 才会启用无模型的离线向量。

Agent 实际获得七个真实工具：五个由 `rag-tools` 模块公布的知识库检索工具（`search_knowledge_base`、`hybrid_search_knowledge_base`、`keyword_search_knowledge_base`、`list_knowledge_documents`、`read_knowledge_document`），以及 `create_file` 和 `save_conversation_to_knowledge_base`。选择知识库后，提示词要求先检索；未检索就收尾时最多追加两次提醒，并留下 `retrieval_guard` span，提醒耗尽仍可能返回未检索答案。回退顺序依赖模型遵循提示词，每轮只执行一次知识库检索。工具循环默认最多 10 轮。

当前向量存储是 SQLite 保存 JSON 向量、NumPy 点积排序，不是 FAISS/Chroma；检索范围过滤不等于用户鉴权。SSE 在完整答案生成后一次返回，尚非逐 token 流式生成。聊天历史在进程内按用户/会话保存，SQLite 记忆尚未严格按会话隔离；这些边界均需在展示时说明。

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

`Jenkinsfile` 假设 Jenkins agent 运行在目标 Linux Docker 主机且有 Docker/Compose 权限。流水线执行模块单测、Linux 编译、严格契约测试、应用端到端测试和二进制运行边界验证；然后归档 `dist/ai-rag-platform-<version>-<platform>.zip`、SHA-256 与逐文件清单。`DeployDemo` 和 `DeployPublicDemo` 默认关闭，分别选择私有工作区与独立公开服务。候选健康检查或 smoke 失败时恢复旧镜像并重建容器；该流程不删除原服务命名卷。部署回滚测试在 Docker builder 阶段运行。ZIP 内不含 `modules-src/`。

公开演示使用 `compose.public-demo.yaml`，只监听服务器回环地址 `18106`，由主页反代到 `/projects/apps/rag/`。`PUBLIC_DEMO=1` 限定 CMRC2018、八个精选问题和五个只读检索工具；响应必须带成功检索来源，每次实际计算使用独立上下文。页面展示真实 provider、hash 检索基线、原始 trace 和五分钟缓存，不接受浏览器密钥或私人文件。DeepSeek 凭据保存在仓库外的服务器环境文件中，缺少凭据时拒绝启动。接口见 [`contracts/WEB_DEMO.md`](contracts/WEB_DEMO.md)。
