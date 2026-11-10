# rag-tools

RAG 工具模块。它把 `rag_core` 的检索原语包装成五个 LLM 可直接调用的工具，
让模型在一次检索失败后还有别的检索方式可以退，而不是只能改写同一个查询词。

模块原名 `rag-skill`；改名是因为它提供的是**工具**，提示词层面的技能在
`skills/rag-retrieval/SKILL.md`。

## 五个工具

| 工具名 | 作用 | 底层实现 |
| --- | --- | --- |
| `search_knowledge_base` | 向量语义检索，默认入口 | `rag_core.retrieve` |
| `hybrid_search_knowledge_base` | 向量与关键词 RRF 融合检索 | `rag_core.hybrid_search` |
| `keyword_search_knowledge_base` | 词面精确匹配，可锁定原文术语 | `rag_core.keyword_search` |
| `list_knowledge_documents` | 列出知识库实际收录的文档 | `rag_core.list_documents` |
| `read_knowledge_document` | 按 `source_id` 分页读取原文（默认 20 块，上限 100） | `rag_core.document_info` + `rag_core.read_document` |

## 接口

```python
from rag_tools import RagTools

rag_tools = RagTools(store=vector_store, tracing=trace_store, top_k=5)

for definition in rag_tools.tool_definitions():
    tools.register(definition, handler_for(definition.name), context_aware=True)

payload = rag_tools.keyword_search(ctx, "奥卡姆剃刀", ["cmrc2018-demo"])
```

每个方法返回 UTF-8 JSON 字符串，包含 `tool`、`query`、`hit_count` 和带来源的
`citations`；`list_documents` 返回 `document_count` 与 `documents`；
`read_document` 额外返回 `offset`、`max_chunks`、`returned_chunks`、`total_chunks`、
`truncated` 与 `next_offset`。

## 分页：不允许一次读全文

`read_knowledge_document` 是分页接口，**一次调用拿不到整篇长文档**：默认 20 块，单次上限 100 块。
被截断时返回 `"truncated": true` 和 `"next_offset"`，调用方必须用它作为新的 `offset` 继续读。
工具描述里已把这条写死，避免模型误以为已经看到全文。

## 范围约束

`knowledge_base_ids` 永远由调用方根据当前请求注入，模型无法通过工具参数查看或修改它。
`read_document` 会额外校验：`source_id` 的第一段必须属于当前所选知识库，否则抛出
`ValueError("source_id 不在当前知识库范围内")`。

`top_k` 的有效范围为 1–20。每次调用记录且只记录一个 `span="rag"` 的 `SpanEvent`，
其 `meta` 含 `tool`、`query`、`knowledge_base_ids`、`hit_count` 与 `hits`。
