# storage

SQLite 持久层：文档向量、按用户隔离的 JSON 状态，以及兼容的记忆/评测组合接口。
SqliteVectorStore 用 JSON 保存向量，NumPy 点积排序；按 source_id 原子替换。
StateStore 只通过 RequestContext 用户范围读写。所有连接使用锁并支持显式关闭。
本包依赖共享接口规范与 NumPy，不依赖 rag_core。PostgreSQL/pgvector 尚未实现。
