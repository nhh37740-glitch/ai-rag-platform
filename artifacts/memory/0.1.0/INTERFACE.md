# INTERFACE

- `MemoryStore.get(ctx, namespace, key) -> MemoryEntry | None`
- `MemoryStore.write(ctx, namespace, key, content, importance) -> MemoryEntry`
- `MemoryStore.search(ctx, namespace, query, top_k) -> list[MemoryEntry]`
- `MemoryStore.forget(ctx, namespace, key) -> None`
- `make_memory(db_path) -> MemoryStore`
