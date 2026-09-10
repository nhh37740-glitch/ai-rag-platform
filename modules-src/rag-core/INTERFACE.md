# INTERFACE

- `embed(texts) -> list[list[float]]`
- `InMemoryVectorStore.add(source_id, chunks, embeddings)` / `search(embedding, top_k, scopes=None)`
- `retrieve(ctx, query, store, scope='kb', top_k) -> RetrievalResult`；`scope` 可传一个或多个知识库标识
- `build_context(result) -> str`
