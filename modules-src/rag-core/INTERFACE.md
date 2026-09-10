# INTERFACE

- `embed(texts) -> list[list[float]]`
- `InMemoryVectorStore.add(source_id, chunks, embeddings)` / `search(embedding, top_k)`
- `retrieve(ctx, query, store, scope='kb', top_k) -> RetrievalResult`
- `build_context(result) -> str`
