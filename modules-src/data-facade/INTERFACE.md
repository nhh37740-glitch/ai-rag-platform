# DataService 0.3.1

Normative API is registered in `specifications/DOMAIN_INTERFACES.md` and `API_SCHEMA.json`.

`DataService(database_path)` owns one SQLite connection shared by memory, vectors, state, notebooks, conversations and generic agent data. A new file receives exactly six tables. An existing file must match all expected tables, columns, primary/unique keys, checks and foreign keys; mismatch raises RuntimeError without altering it. There is no legacy migration.

The service exposes user CRUD, site-wide atomic quota reservations, user-scoped conversation CRUD, notebook/member CRUD (viewer/editor), agent_data access, and the existing MemoryStore/StateStore/VectorStore/NotebookStore facades. Close is idempotent and closes the shared connection once.

模型切换时，replace_all_embeddings(ctx,replacements) 在同一事务中替换所有文档向量；文本块保持原样。

## 0.3.2 来源删除

delete_document(ctx, notebook_id: str, source_id: str) -> None；两个范围精确匹配，原子删除来源全部分块，不存在或跨范围抛ValueError。HTTP在调用前通过auth-facade复核owner/editor权限。
