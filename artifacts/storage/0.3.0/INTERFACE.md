# INTERFACE

Version 0.3.0. All port types are imported from core_specifications; no dependency on RAG.

- `SqliteVectorStore(db_path: str)`
- `SqliteVectorStore.add(source_id: str, chunks: List[str], embeddings: Any) -> None`
- `SqliteVectorStore.search(embedding: Any, top_k: int = 5, scopes: Optional[List[str]] = None) -> List[tuple[str, str, float]]`
- `SqliteVectorStore.list_documents(scopes: Optional[List[str]] = None) -> List[tuple[str, int]]`
- `SqliteVectorStore.document_chunks(source_id: str) -> List[str]`
- `StateStore(db_path: str)`
- `StateStore.get(ctx: RequestContext, key: str) -> Any`
- `StateStore.set(ctx: RequestContext, key: str, value: Any) -> None`
- `StateStore.delete(ctx: RequestContext, key: str) -> None`
- `StateStore.increment_if_below(ctx: RequestContext, key: str, limit: int) -> Optional[int]`

Counters share the user-scoped state table. increment_if_below uses BEGIN IMMEDIATE to atomically reserve across independent connections/processes, returns the new integer, or None when exhausted. Missing counters start at zero; malformed counters and invalid positive-integer limits fail without modifying state.
- `SqliteVectorStore/StateStore/Storage.close() -> None`

Vectors use SQLite JSON plus NumPy dot-product ranking. add atomically replaces all chunks for one source.
Validation checks counts, non-empty finite vectors and consistent collection dimensions before any deletion.
An empty chunk/vector pair clears that source. scope=None searches all, scope=[] searches none.
top_k must be a positive integer, excluding bool. State values are user-scoped JSON; missing keys return None.
All owned connection access is locked. close is idempotent and all later operations raise RuntimeError.
Legacy Storage closes its own evaluation connection and leaves injected stores caller-owned.

- `Storage.memory_write/get/search/forget(ctx, namespace, ...)`
- `Storage.add_documents(source_id, chunks, embeddings)` / `search_documents(query_embedding, top_k)`
- `Storage.save_eval(run_id, payload)` / `load_eval(run_id)`
- `make_storage(db_path, memory_store, vector_store)`
