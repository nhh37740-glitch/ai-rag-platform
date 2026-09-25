# rag_core

RAG 检索核心：`VectorStore` 契约、`RagClient` 门面、内存/SQLite 向量库、可切换向量化，以及按知识库范围过滤的检索与引用。默认由 FastEmbed 运行 `BAAI/bge-small-zh-v1.5`；模型不可用时直接报错，不会静默切换为 hash。

检索提供四条路径：`retrieve`（向量语义）、`keyword_search`（纯词面，不需要模型）、`hybrid_search`（两者 RRF 融合）、`read_document`（按 source_id 分页读原文），外加 `list_documents` 用于枚举范围内文档。

## 分页读取

`read_document(ctx, store, source_id, max_chunks=DEFAULT_READ_CHUNKS, offset=0)` 是**分页**接口：
默认只返回 `DEFAULT_READ_CHUNKS`（20）块，单次调用最多 `MAX_READ_CHUNKS`（100）块，
所以一次调用不可能把整篇长文档读回来。每个 `Citation.metadata` 带 `chunk_index`（1 起绝对序号）
与 `total_chunks`，调用方据此决定要不要用更大的 `offset` 继续读。

`document_info(ctx, store, source_id)` 返回 `{source_id, title, knowledge_base_id, chunk_count}`，
用来在读取前确认一共有多少块；未知 `source_id` 的 `chunk_count` 为 0。
