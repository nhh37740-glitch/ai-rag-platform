# INTERFACE

- `embed(texts) -> list[list[float]]`：默认 FastEmbed + `BAAI/bge-small-zh-v1.5`，不可用时报错；`RAG_EMBED=hash` 才启用 hash
- `VectorStore`：统一的 `add/search` 协议
- `InMemoryVectorStore.add(source_id, chunks, embeddings)` / `search(embedding, top_k, scopes=None)`
- `VectorStore.list_documents(scopes=None) -> list[tuple[source_id, chunk_count]]`（按 source_id 升序）
- `VectorStore.document_chunks(source_id) -> list[str]`（按写入顺序；不存在返回空列表）
- `SqliteVectorStore(db_path)`：与内存实现相同接口的持久化向量库
- `RagClient(store, embed_fn=embed, top_k=5)` / `retrieve(ctx, query, scope='kb', top_k=None)`
- `retrieve(ctx, query, store, scope='kb', top_k) -> RetrievalResult`；`scope` 可传一个或多个知识库标识
- `keyword_search(ctx, query, store, scope='kb', top_k=5) -> RetrievalResult`：纯词面打分，不需要向量模型
- `hybrid_search(ctx, query, store, scope='kb', top_k=5, alpha=0.5) -> RetrievalResult`：向量与词面 RRF 融合
- `list_documents(ctx, store, scope='kb') -> list[dict]`：`{source_id,title,knowledge_base_id,chunk_count}`
- `read_document(ctx, store, source_id, max_chunks=50) -> RetrievalResult`：按 source_id 取全文块
- `build_context(result) -> str`
