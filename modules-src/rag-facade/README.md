# rag-facade

RAG 业务模块负责文档解析、切分、嵌入、入库、检索与追踪。应用层通过公开的 `RagService` 使用能力，不直接调用 `ingestion`、`rag-core`、`rag-tools` 或 `observability`。
