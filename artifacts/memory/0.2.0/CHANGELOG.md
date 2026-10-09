# Changelog

## [0.2.0]
- Serialize SQLite access and add idempotent close; closed stores reject all operations.
- Replace duplicate namespace/user/key writes atomically while keeping the existing table format.
- Type RequestContext explicitly and validate search top_k.

## [0.0.0]
- 初始化版本。`n
