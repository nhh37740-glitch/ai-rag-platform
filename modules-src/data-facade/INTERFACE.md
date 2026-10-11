# DataService 0.3.0

Normative API is registered in `specifications/DOMAIN_INTERFACES.md` and `API_SCHEMA.json`.

`DataService(database_path)` owns one SQLite connection shared by memory, vectors, state, notebooks, conversations and generic agent data. A new file receives exactly six tables. An existing file must match all expected tables, columns, primary/unique keys, checks and foreign keys; mismatch raises RuntimeError without altering it. There is no legacy migration.

The service exposes user CRUD, site-wide atomic quota reservations, user-scoped conversation CRUD, notebook/member CRUD (viewer/editor), agent_data access, and the existing MemoryStore/StateStore/VectorStore/NotebookStore facades. Close is idempotent and closes the shared connection once.
