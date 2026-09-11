# Changelog

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
