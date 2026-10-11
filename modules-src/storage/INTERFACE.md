# INTERFACE

Version 0.5.0. All stores accept a shared sqlite3.Connection and shared lock from DataService. They never create tables on an existing database. A standalone path opens only a new six-table database or rejects an incompatible schema.

- `SqliteVectorStore.add/search/list_documents/document_chunks`: vector API backed by `documents` JSON embeddings and dot-product ranking.
- `StateStore.get/set/delete/increment_if_below`: user-scoped JSON values in `agent_data`; counters use `BEGIN IMMEDIATE`.
- `NotebookStore`: user, notebook and member CRUD in the corresponding tables; member roles are only `editor` and `viewer`.
- `close()` marks an injected wrapper closed; only the connection owner closes SQLite.

Exactly six tables are accepted: users, notebooks, notebook_members, documents, conversations, agent_data. Existing extra tables or mismatched columns/keys/checks/foreign keys raise RuntimeError. No migration or old ACL import is performed.
