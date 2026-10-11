# data-facade

## 0.2.0 — 2026-10-11

新增笔记本目录业务接口和NotebookStorePort；统一创建、读取、幂等迁移、改名、软归档生命周期，应用经业务接口消费。

# Changelog

## [0.1.0]
- Add DataService database domain composition through shared ports.
- Lazily create and reuse memory/vector/state stores with persistent SQLite defaults.
- Release all owned connections on close, guard use after close and clean up failed initialization.
