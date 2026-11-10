# 代码树与目录职责

本文是面向人类读者的顶层导航。接口与业务事实仍以
[`docs/PLAN.md`](PLAN.md) 和 [`specifications/INTERFACES.md`](../specifications/INTERFACES.md)
为准；目录约束由 `scripts/check_repo_structure.py` 自动检查。

## 顶层视图

```text
ai-rag-platform/
├── specifications/        # 接口规范层（唯一共享源码；运行时只读）
├── modules-src/           # 模块源码层（仅构建阶段；运行镜像不包含）
│   ├── agent/             #   智能体编排、工具、技能、MCP、模型网关
│   ├── rag/               #   解析、分块、检索、RAG 门面
│   ├── data/              #   持久化、向量/记忆、数据门面
│   ├── auth/              #   账号、会话、鉴权
│   └── platform/          #   跨域可观测性
├── artifacts/             # 编译产物层（运行时只读；按模块/版本）
├── registry.json          # 模块版本、checksum 与产物路径索引
├── apps/                  # 集成应用层（RAGnotebook HTTP + Web）
├── scripts/               # 结构/依赖检查、测试、编译、部署与运维
├── skills/                # 运行时 Skill 资源
├── data/                  # 演示知识库与运行时数据（不进入镜像的私有数据）
├── docs/                  # 方案、架构、验证记录与运维文档
├── compose.yaml           # 单服务部署定义
├── Dockerfile             # 多阶段构建：源码测试 → 编译 → 运行
└── Jenkinsfile            # 构建、真实模型门禁与可选发布
```

## 架构层级

| 层级 | 目录 | 谁读 | 是否进入运行镜像 | 允许依赖 |
|---|---|---|---|---|
| 接口规范 | `specifications/` | 所有模块、应用 | 是 | 无（只依赖标准库） |
| 模块源码 | `modules-src/<域>/<模块>/` | 构建、模块测试 | 否 | 本域模块、公共规范、platform |
| 编译产物 | `artifacts/<模块>/<版本>/` | 运行时加载器 | 是 | 无（只被加载） |
| 集成应用 | `apps/ragnotebook/` | 浏览器、部署 | 是 | 四个业务 facade、公共规范 |
| 前端 | `apps/web/` | 浏览器 | 是 | 只调用 HTTP API |
| 运维脚本 | `scripts/` | 开发者、Jenkins | 部分 | 仓库路径与部署环境 |

## 业务域与模块

| 业务域 | 职责 | 模块 |
|---|---|---|
| `agent/` | 问答编排、工具、技能、MCP、模型调用 | agent-facade, agent-runtime, evaluation, llm-gateway, mcp-gateway, mcp-servers, skill-runtime, tool-runtime |
| `rag/` | 文档解析、分块、嵌入、检索 | rag-facade, rag-core, rag-tools, ingestion |
| `data/` | 唯一 SQLite、向量/记忆、会话 | data-facade, storage, memory |
| `auth/` | 账号、登录、额度、权限 | auth-facade, auth-runtime |
| `platform/` | 跨域可观测性 | observability |

每个业务域的读者入口是该域 `README.md`；公开接口入口是该域 `*-facade/INTERFACE.md`。

## 依赖边界

```text
apps/ragnotebook ──► 四个业务 facade ──► 本域 runtime/能力模块 ──► core_specifications
        │                    │
        └────────────────────┴──► platform/observability（只读日志/trace）
```

- 应用不得导入一级模块、SQLite 或向量实现。
- 业务域之间不得直接导入对方实现；跨域服务通过注入的 Protocol 使用。
- `auth-runtime` 只允许 `core_specifications` 与标准库。
- 运行时只从 `artifacts/` 加载 `.pyd/.so`；从 `modules-src/` 或 `.py` 加载会拒绝启动。

## 重整前后对照（2026-11）

| 重整前 | 重整后 |
|---|---|
| `modules-src/agent-facade/` | `modules-src/agent/agent-facade/` |
| `modules-src/agent-runtime/` | `modules-src/agent/agent-runtime/` |
| `modules-src/evaluation/` | `modules-src/agent/evaluation/` |
| `modules-src/llm-gateway/` | `modules-src/agent/llm-gateway/` |
| `modules-src/mcp-gateway/` | `modules-src/agent/mcp-gateway/` |
| `modules-src/mcp-servers/` | `modules-src/agent/mcp-servers/` |
| `modules-src/skill-runtime/` | `modules-src/agent/skill-runtime/` |
| `modules-src/tool-runtime/` | `modules-src/agent/tool-runtime/` |
| `modules-src/rag-facade/` | `modules-src/rag/rag-facade/` |
| `modules-src/rag-core/` | `modules-src/rag/rag-core/` |
| `modules-src/rag-tools/` | `modules-src/rag/rag-tools/` |
| `modules-src/ingestion/` | `modules-src/rag/ingestion/` |
| `modules-src/data-facade/` | `modules-src/data/data-facade/` |
| `modules-src/storage/` | `modules-src/data/storage/` |
| `modules-src/memory/` | `modules-src/data/memory/` |
| `modules-src/auth-facade/` | `modules-src/auth/auth-facade/` |
| `modules-src/auth-runtime/` | `modules-src/auth/auth-runtime/` |
| `modules-src/observability/` | `modules-src/platform/observability/` |

模块 ID、包名、公开接口、版本和 `artifacts/` 路径均未改变；只改变了源码在
`modules-src/` 中的阅读层级。历史验证文档中的旧路径保留为当时记录。

## 自动校验

```bash
python scripts/check_repo_structure.py   # 顶层、业务域、artifacts/registry、导航文档
python scripts/check_module_dependencies.py  # 导入方向与循环依赖
```

新增模块或目录时，先更新 `scripts/repo_layout.py` 的 `MODULE_GROUPS`，再更新本文和
对应业务域 `README.md`。
