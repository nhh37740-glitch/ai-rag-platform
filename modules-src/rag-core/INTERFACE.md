# INTERFACE

- `embed(texts) -> list[list[float]]`
- `VectorStore`：统一的 `add/search` 协议
- `InMemoryVectorStore.add(source_id, chunks, embeddings)` / `search(embedding, top_k, scopes=None)`
- `SqliteVectorStore(db_path)`：与内存实现相同接口的持久化向量库
- `RagClient(store, embed_fn=embed, top_k=5)` / `retrieve(ctx, query, scope='kb', top_k=None)`
- `retrieve(ctx, query, store, scope='kb', top_k) -> RetrievalResult`；`scope` 可传一个或多个知识库标识
- `build_context(result) -> str`
