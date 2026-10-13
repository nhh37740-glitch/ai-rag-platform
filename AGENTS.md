# Repository Guidelines

## 项目目的

本仓库用于构建 **企业研发知识与协作智能体系统（Dev Knowledge Agent）**。核心能力是"会问答、会调工具、会走流程、记得住上下文"，并把它做成**接口规范先行 + 源码隔离 + 二进制交付**的模块化系统。Docker 构建阶段使用模块源码编译；运行镜像只消费接口规范与编译后的二进制。

> 唯一事实来源是 [`docs/PLAN.md`](docs/PLAN.md)。改方案先改它，再动代码。

## 结构约定

```text
specifications/       # 接口规范层（唯一共享"源码"）：core-specifications + INTERFACE.md + API_SCHEMA.json + test_specification.py
modules-src/     # 各模块源码包（构建阶段可见，运行阶段不进入镜像）
artifacts/       # 集成 Agent 只读：模块/版本/ 下的二进制 + 接口规范文档 + checksum
registry.json    # 各模块版本 + checksum 索引
apps/            # 集成 Agent 编写：agent-server(FastAPI) + web/ 静态前端
docs/            # PLAN.md 与 architecture/ 说明
```

命名约定：模块目录用 `kebab-case`（如 `rag-core`、`tool-runtime`）；当前 Git 发布单元是根目录仓库。各模块以独立 Python 包、接口规范和版本维护，模块目录不是独立 Git 仓库。部分目录含历史本地 `.git`，但没有远程仓库，不应将其误认为已发布的独立仓库。

## 架构原则

- **接口规范先行**：所有接口先写进 `specifications/`，类型化签名固定后再实现。
- **源码隔离**：实现源码放 `modules-src/`，集成侧只消费 `artifacts/` 里的二进制与接口规范。运行时不使用 editable 源码模式：`apps/ragnotebook/runtime_boundary.py` 在导入业务模块前读取 `registry.json`，只把 `published` 的 `artifacts` 路径加入运行时，并在导入后校验每个模块确实来自 `.pyd/.so`；任何模块若从 `modules-src` 或 `.py` 加载，服务立即拒绝启动。源码只用于编译和模块单测。
- **二进制交付**：当前 Jenkins/Linux 路径用 Cython 编译进程内模块成 `.so`，Windows 目标为 `.pyd`；Windows 手动 worker 交付可用 Nuitka 生成 `.exe`。实际交付形式以 `specifications/API_SCHEMA.json` 与流水线配置为准。
- **进程/线程**：`agent-server` 内走接口直调 + asyncio/`asyncio.to_thread`；真正独立的模块（ingestion-worker、MCP servers）才拆成独立进程。
- **存储**：统一 `storage` 接口是后续架构目标。当前 Web 通过 data-facade 使用 memory/storage 的 SQLite、JSON 向量与 NumPy 排序；`storage` 已注册进入运行链路，FAISS/Chroma、PostgreSQL+pgvector 切换尚未实现。实际能力以 `docs/PLAN.md` 为准。
- **可观测**：所有模块接收 `RequestContext(trace_id, request_id, user_id, session_id)`，打结构化日志 + span 耗时；`GET /api/trace/{trace_id}` 看全链路。

## 构建、测试与运行

模块仍在同一个根仓库中，源码测试显式加载源码，编译后回放同一套模块测试；集成服务只消费二进制：

```bash
# 接口规范/端到端（在集成侧）
python scripts/run_tests.py --mode source --group leaf
python scripts/run_tests.py --mode source --group facade
python scripts/run_tests.py --mode binary --group specification
python scripts/verify_compiled_runtime.py
```

## 提交与 PR 规范
- 每次开始新版本前，先明确项目版本号，从当前 `master` 建独立分支；完成后通过 PR 合回 `master`。
- 每个 RAG PR 按三级应用 `RAGnotebook` → 二级业务模块 → 本次实际修改的一级模块的顺序，说明用户可见功能、业务接口、各一级模块为该功能做的具体修改；只被调用而未修改的模块必须标为“沿用”，不得写成修改。
- 使用 Conventional Commits：`feat:` `fix:` `docs:` `test:` `build:`。
- 模块改动 = 根仓库一次提交 + bump `VERSION` + 更新 `CHANGELOG.md` + 在目标平台重建二进制与 `checksum`。
- PR 描述需说明：模块实现什么、接口是否变化、如何运行、对应哪条岗位要求。
- 集成侧运行镜像只包含 `specifications/`、`apps/`、`artifacts/` 等运行资产，不包含 `modules-src/`。模块实现改动仍按接口规范、版本与测试流程审查。
- 提交前检查：`AGENTS.md` 与 `docs/PLAN.md` 是否为最新事实；所有改动链路（版本、checksum、接口规范测试）一致。

## 业务依赖（RAGnotebook 重构，2026-10-11）

- 唯一应用入口命名为 `RAGnotebook`，浏览器只调用其 HTTP API；一个服务进程内组合 auth-facade、data-facade、rag-facade、agent-facade。
- `RAGnotebook` 只可导入四个业务 facade 与共享公共接口/observability；不得导入一级业务模块、sqlite/storage 类、具体向量/记忆实现。
- 二级业务模块经公开接口互调；auth-facade 可调用 data-facade 的公开数据 API；rag-facade 可调用 data-facade；agent-facade 只调用公开 data/rag API。每个一级模块仅归一个业务模块：auth-runtime→auth-facade；storage、memory→data-facade；rag-core、rag-tools、ingestion→rag-facade；agent-runtime、llm-gateway、skill-runtime、tool-runtime、mcp-gateway、mcp-servers、evaluation→agent-facade。
- data-facade 是唯一持久化入口，六张关系表与所有向量/记忆/会话/Agent 数据共用一个 SQLite 文件。禁止创建多个 DB 文件、额外 schema 表或自动迁移。确有必要改表时，先获用户确认并更新冻结方案。
- 用户本地注册；单次初始化管理员与固定游客。笔记本 owner 是资源所有者，不是全局管理员；成员角色仅 editor/viewer。登录令牌仅进程内，服务重启后重新登录。访客聊天不持久化；全站每日额度100次。
- 改实现前先读 `docs/PLAN.md` 和 `specifications/DOMAIN_INTERFACES.md`；签名/Schema 先登记，再改实现、对应单测、版本、CHANGELOG 与工件索引。源码改动仅在服务器独立 Git 分支进行，按当前业务任务与用户授权推进；视频平台项目不属于本仓库任务。

## Code Review Rules

### 应用调用边界
- 检查 `RAGnotebook` HTTP/Web 代码是否绕过四个 facade 的公开接口直接调用一级模块、SQLite 或向量存储。安全做法是通过归属业务模块的公开接口完成操作。

### 单库与权限
- 检查改动是否新增第二个数据库文件、额外业务表或自动迁移，或让游客历史持久化、禁用账号通过鉴权。安全做法是保持已冻结六表结构、统一 data-facade 存储，并在每次请求中复核账号有效状态。
