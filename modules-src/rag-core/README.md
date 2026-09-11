# rag_core

RAG 检索核心：`VectorStore` 契约、`RagClient` 门面、内存/SQLite 向量库、可切换向量化，以及按知识库范围过滤的检索与引用。默认由 FastEmbed 运行 `BAAI/bge-small-zh-v1.5`；模型不可用时直接报错，不会静默切换为 hash。
