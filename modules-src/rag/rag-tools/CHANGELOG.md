# 0.3.1
- 共享接口包迁移为 core_specifications；重新构建二进制并保持本模块接口行为。

# Changelog

## [0.3.0] - 2026-09-11

- `read_knowledge_document` 改为分页读取：新增 `offset` 与 `max_chunks` 参数，默认只返回 20 块，一次调用不可能读回整篇长文档。
- 返回值新增 `offset`、`max_chunks`、`returned_chunks`、`total_chunks`、`truncated`、`next_offset`，模型据此续读。
- 工具描述明确要求：`truncated` 为 true 时必须用 `next_offset` 继续读，不得假设已拿到全文。
- `rag` span 在 read 场景额外记录 `offset`、`max_chunks`、`truncated`。

## [0.2.0] - 2026-09-11

- 模块由 `rag-skill` 改名为 `rag-tools`：它提供的是 LLM 可调用的工具，不是提示词技能；包名 `rag_skill` → `rag_tools`，类名 `RagSkill` → `RagTools`。
- 工具由一个扩展为五个：`search_knowledge_base`、`hybrid_search_knowledge_base`、`keyword_search_knowledge_base`、`list_knowledge_documents`、`read_knowledge_document`。
- 新增 `tool_definitions()` 一次返回全部工具定义，供服务端注册。
- 每个工具返回带 `tool` 字段的 JSON 载荷，并记录一个带 `tool` 字段的 `rag` span。
- `read_knowledge_document` 增加硬范围校验：`source_id` 不属于当前所选知识库时直接报错。
- 删除旧的 `tool_definition()` 与 `execute()` 兼容入口。

## 0.1.0 - 2026-09-11

- 新增 `search_knowledge_base` Agent 工具定义。
- 新增请求级知识库范围约束与 1–20 的 `top_k` 限制。
- 新增结构化检索结果及成功、失败 `rag` trace 记录。
