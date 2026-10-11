# DataService 0.1.0

The normative shared signatures and D01-D05 requirements are in specifications/DOMAIN_INTERFACES.md.

- DataService(state_dir: str, memory_db_path: str | None = None, vector_db_path: str | None = None)
- initialize(ctx: RequestContext) -> None
- memory_store(ctx: RequestContext) -> MemoryStorePort
- vector_store(ctx: RequestContext) -> VectorStore
- state_db(ctx: RequestContext) -> StateStorePort
- close(ctx: RequestContext) -> None

First access creates missing directories and SQLite files (memory.sqlite, vectors.sqlite, state.sqlite).
Optional memory/vector paths accept :memory:. Repeated initialization or access returns the same stores.
Only this facade owns their lifecycle. close is idempotent; subsequent facade or store access raises RuntimeError.
State values are JSON and isolated by ctx.user_id; missing keys return None.
SQLite vectors replace all chunks for one source in a transaction, and failed validation preserves prior data.
No implementation depends on rag_core or another intermediate domain package.

0.2.0 新增 notebook_store(ctx)->NotebookStorePort，create_notebook/get_notebook/list_notebooks/migrate_notebook/update_notebook/set_notebook_archived；签名见API_SCHEMA.json。关系目录保存在 notebook.sqlite，关闭时与其它三个owned stores一起释放；角色决策由auth-facade执行，DataService不授予权限。
