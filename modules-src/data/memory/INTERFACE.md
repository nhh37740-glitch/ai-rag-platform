# INTERFACE

Version 0.3.0. MemoryStore accepts the DataService-owned SQLite connection and lock; its records are namespaced in the shared `agent_data` table.

- `get(ctx, namespace, key) -> MemoryEntry | None`
- `write(ctx, namespace, key, content, importance=0.0) -> MemoryEntry`
- `search(ctx, namespace, query, top_k=5) -> list[MemoryEntry]`
- `forget(ctx, namespace, key) -> None`
- `close() -> None`

`make_memory(db_path)` is available for standalone tests and accepts only a new six-table database or a matching existing database.
