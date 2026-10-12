# rag-facade 0.3.0

`RagService` 提供文档解析、切分、嵌入、入库、检索和追踪读取。它依赖 VectorStore 端口、`ingestion`、`rag-core`、`rag-tools` 与 `observability`。持久化由 `data-facade` 提供。

构造：`RagService(store: VectorStore, tracing: TraceStorePort | None = None, top_k: int = 5, embedding_state: DataServicePort | None = None)`。未传入 tracing 时，由 RAG 业务模块创建进程内追踪存储。`record(span)` 和 `get(trace_id)` 暴露追踪业务接口，供同一问答链路记录和读取事件；HTTP 应用不直接导入 `observability`。

`ensure_embedding_model(ctx)` 使用 `embedding_state` 的公开 DataService 接口，在 `agent_data` 保存 `RAG_EMBED` 和 BGE 模型标识。标识变化后按每篇文档已有分块重新生成并替换向量，成功后才更新标识；不增删表。

支持 md/txt/docx/pdf。检索范围必须显式提供；空范围不返回文档。文档按页读取，每次最多 100 个分块。`ingest` 接收服务端临时文件路径，完成解析、切分、嵌入和入库。
