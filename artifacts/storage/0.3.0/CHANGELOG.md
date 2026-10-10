# Changelog

## [0.3.0]
- Add durable atomic bounded counters through the shared state-store port.

## [0.2.0]
- Own persistent SQLite vector implementation; remove dependency on rag_core.
- Atomically replace vectors per source; validate counts, dimensions and finite values before writes.
- Add user-scoped JSON StateStore and idempotent connection close with locked access.
- Preserve Storage/make_storage compatibility through shared memory/vector interfaces.
