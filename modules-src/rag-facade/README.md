# rag-facade

RAG 业务模块负责文档解析、切分、嵌入、入库、检索与追踪。应用层通过公开的 `RagService` 使用能力，不直接调用 `ingestion`、`rag-core`、`rag-tools` 或 `observability`。

启动时由 `ensure_embedding_model` 比对向量模型标识；模型改变时从六表数据库中的现存文本块重建向量，并把标识存到 `agent_data`，不改 schema。
