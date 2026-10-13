## 0.5.0 - 2026-10-11

- Use the shared six-table SQLite schema and connection; add account, site quota, conversation, notebook membership, and agent data APIs. Reject incompatible databases; no legacy migration.

# storage

## 0.4.0 — 2026-10-11

新增NotebookStore与users/notebooks/notebook_members/roles/permissions/role_permissions/schema_migrations表；外键、唯一约束、事务回滚、版本比较更新、迁移标记和归档持久化。

# Changelog

## [0.3.0]
- Add durable atomic bounded counters through the shared state-store port.

## [0.2.0]
- Own persistent SQLite vector implementation; remove dependency on rag_core.
- Atomically replace vectors per source; validate counts, dimensions and finite values before writes.
- Add user-scoped JSON StateStore and idempotent connection close with locked access.
- Preserve Storage/make_storage compatibility through shared memory/vector interfaces.
