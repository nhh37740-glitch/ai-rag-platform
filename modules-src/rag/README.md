# rag — 检索增强生成业务域

负责文档解析、分块、嵌入、入库与检索。读者入口是 `rag-facade/INTERFACE.md`；
集成侧只通过 `RagService` 调用本域。

| 模块 | 职责 |
|---|---|
| `rag-facade` | 本域唯一公开门面：导入、检索、来源与 trace |
| `rag-core` | 分块、嵌入、向量检索与排序算法 |
| `rag-tools` | 暴露给智能体的 RAG 工具适配 |
| `ingestion` | 独立进程：目录解析→分块→embed→写索引 |

允许依赖：本域模块、`core_specifications`、`platform/observability`。
向量/记忆的持久化通过 `data-facade` 注入的端口使用，不直接依赖 `data/` 实现。
