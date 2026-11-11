## 0.3.1 - 2026-10-13

## 0.3.2 — 2026-10-13

- 增加笔记本范围内删除来源的公开业务接口，事务删除全部分块。

- Expose atomic full-collection vector replacement through the business API.

## 0.3.0 - 2026-10-11

- Use the shared six-table SQLite schema and connection; add account, site quota, conversation, notebook membership, and agent data APIs. Reject incompatible databases; no legacy migration.

# data-facade

## 0.2.0 — 2026-10-11

新增笔记本目录业务接口和NotebookStorePort；统一创建、读取、幂等迁移、改名、软归档生命周期，应用经业务接口消费。

# Changelog

## [0.1.0]
- Add DataService database domain composition through shared ports.
- Lazily create and reuse memory/vector/state stores with persistent SQLite defaults.
- Release all owned connections on close, guard use after close and clean up failed initialization.
