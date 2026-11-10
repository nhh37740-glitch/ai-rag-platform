## 0.3.0 - 2026-10-11

- Use the shared six-table SQLite schema and connection; add account, site quota, conversation, notebook membership, and agent data APIs. Reject incompatible databases; no legacy migration.

# Changelog

## [0.2.0]
- Serialize SQLite access and add idempotent close; closed stores reject all operations.
- Replace duplicate namespace/user/key writes atomically while keeping the existing table format.
- Type RequestContext explicitly and validate search top_k.

## [0.0.0]
- 初始化版本。`n
