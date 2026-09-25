# Changelog

## [0.4.1]
- `read_document` 改为强制分页：新增 `offset` 参数，默认只返回 `DEFAULT_READ_CHUNKS=20` 块，单次调用上限 `MAX_READ_CHUNKS=100`，一次调用已不可能读回整篇长文档。
- 新增 `document_info(ctx, store, source_id)`，返回 `{source_id,title,knowledge_base_id,chunk_count}`，供调用方判断分页边界。
- `read_document` 返回的每个 `Citation.metadata` 新增 `chunk_index`（1 起绝对序号）与 `total_chunks`。

## [0.4.0]
- 新增 `keyword_search`：纯词面检索，不依赖向量模型，专有名词与原文术语命中稳定。
- 新增 `hybrid_search`：向量召回与词面召回用 RRF 融合，修正语义模型漏掉原文关键词的问题。
- 新增 `list_documents`：列出范围内的文档清单与块数量，供 Agent 在检索不到时确认知识库内容。
- 新增 `read_document`：按 `source_id` 取回整篇文档原文块，用于定位后核对完整内容。
- `VectorStore` 协议新增 `list_documents` 与 `document_chunks`，`InMemoryVectorStore` 与 `SqliteVectorStore` 同步实现。

## [0.3.0]
- 默认通过 FastEmbed 运行 `BAAI/bge-small-zh-v1.5`，并将 FastEmbed 声明为运行依赖。
- 移除模型加载失败时的静默 hash 降级；hash 后端只能通过 `RAG_EMBED=hash` 显式启用。
- 对缺少运行库、模型加载失败、推理失败和未知后端提供明确错误。

## [0.2.1]
- 按契约补齐并导出 `VectorStore`、`RagClient` 和 `SqliteVectorStore`。

## [0.2.0]
- 支持按一个或多个知识库范围过滤检索，并在上下文中显示文档来源。

## [0.1.0]
- 初始化向量化、内存向量库与检索能力。
