# INTERFACE

- `MemoryStore.get(ctx, namespace, key) -> MemoryEntry | None`
- `MemoryStore.write(ctx, namespace, key, content, importance) -> MemoryEntry`
- `MemoryStore.search(ctx, namespace, query, top_k) -> list[MemoryEntry]`
- `MemoryStore.forget(ctx, namespace, key) -> None`
- `make_memory(db_path) -> MemoryStore`
- `MemoryStore.close() -> None`: idempotent release; get/write/search/forget reject access afterwards.

MemoryStore uses SQLite with locked thread access. Namespace/user/key writes atomically replace old entries.
The existing memory table is compatible. Session namespace continues to use user_id and does not add session_id isolation.
