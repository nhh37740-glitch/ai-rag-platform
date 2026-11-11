# modules-src — 模块源码层

本目录只在构建阶段可见，运行镜像不包含模块源码。模块按**业务域**分组，每组内再按
模块 ID 平铺；每个模块是独立 Python 包，含 `VERSION`、`pyproject.toml`、
`INTERFACE.md`、`API_SCHEMA.json`、`CHANGELOG.md`、包目录和 `tests/`。

```text
modules-src/
├── agent/       智能体编排、工具、技能、MCP 与模型网关
├── rag/         解析、分块、检索与 RAG 门面
├── data/        持久化、向量/记忆存储与数据门面
├── auth/        账号、会话与鉴权
└── platform/    跨域可观测性
```

| 业务域 | 模块 | 读者入口 |
|---|---|---|
| `agent/` | agent-facade, agent-runtime, evaluation, llm-gateway, mcp-gateway, mcp-servers, skill-runtime, tool-runtime | `agent/README.md` |
| `rag/` | rag-facade, rag-core, rag-tools, ingestion | `rag/README.md` |
| `data/` | data-facade, storage, memory | `data/README.md` |
| `auth/` | auth-facade, auth-runtime | `auth/README.md` |
| `platform/` | observability | `platform/README.md` |

## 阅读顺序

1. 先看 `specifications/INTERFACES.md` 与 `specifications/DOMAIN_INTERFACES.md`，确认公开接口；
2. 再看对应业务域的 facade（`*-facade/INTERFACE.md`），它定义该域的调用边界；
3. 最后看该域内的 runtime/能力模块实现。

## 边界

- 集成侧（`apps/ragnotebook`）只导入四个业务 facade 和共享公共接口，不直接导入一级模块。
- 模块之间只能调用对方公开接口；跨域依赖通过注入的 Protocol 完成。
- 构建产物写入 `artifacts/<module-id>/<version>/`，模块目录不是独立 Git 仓库。
- 新增模块必须登记到 `scripts/repo_layout.py` 的 `MODULE_GROUPS`，并更新本文件与
  `docs/CODE_TREE.md`；`python scripts/check_repo_structure.py` 会拒绝未登记目录。
