# rag-tools Interface

版本：0.3.0（原 `rag-skill`）

```python
class RagTools:
    def __init__(self, store: VectorStore, tracing: TraceStore, top_k: int = 5): ...
    def tool_definitions(self) -> list[ToolDef]: ...
    def search(self, ctx: RequestContext, query: str, knowledge_base_ids: list[str],
               top_k: int | None = None) -> str: ...
    def hybrid_search(self, ctx: RequestContext, query: str, knowledge_base_ids: list[str],
                      top_k: int | None = None) -> str: ...
    def keyword_search(self, ctx: RequestContext, query: str, knowledge_base_ids: list[str],
                       top_k: int | None = None) -> str: ...
    def list_documents(self, ctx: RequestContext, knowledge_base_ids: list[str]) -> str: ...
    def read_document(self, ctx: RequestContext, source_id: str,
                      knowledge_base_ids: list[str],
                      offset: int = 0, max_chunks: int | None = None) -> str: ...
```

`tool_definitions()` 按固定顺序返回五个工具：

1. `search_knowledge_base` —— 参数 `query`（必填）、`top_k`（1–20）。
2. `hybrid_search_knowledge_base` —— 参数同上。
3. `keyword_search_knowledge_base` —— 参数同上。
4. `list_knowledge_documents` —— 无参数。
5. `read_knowledge_document` —— 参数 `source_id`（必填）、`offset`（≥0）、`max_chunks`（1–100，默认 20）。

所有工具的 JSON Schema 都是 `additionalProperties: false`；`knowledge_base_ids`
不在参数里，始终由调用方根据当前请求注入。

## 返回值

- 四个检索类方法：`{"tool": str, "query": str, "hit_count": int, "citations": [...]}`
- `list_documents`：`{"tool": str, "document_count": int, "documents": [...]}`
- `read_document`：`{"tool": str, "source_id": str, "query": str, "offset": int, "max_chunks": int,
  "returned_chunks": int, "total_chunks": int, "truncated": bool, "next_offset": int|null,
  "hit_count": int, "citations": [...]}`

`citations` 每项含 `source_id`、`title`、`text`、`score` 与 `metadata`。

## 范围约束

`read_document` 要求 `source_id.partition("/")[0]` 属于当前所选知识库，否则抛出
`ValueError("source_id 不在当前知识库范围内")`。

## 分页约束

`read_knowledge_document` **绝不允许一次读完整篇文档**：默认只返回 `rag_core.DEFAULT_READ_CHUNKS`（20）块，
单次上限 `rag_core.MAX_READ_CHUNKS`（100）块。`truncated` 为 true 时调用方必须用 `next_offset`
作为新的 `offset` 继续读取，直到 `truncated` 为 false。这样大文档不会一次撑爆上下文。

## 追踪

每次调用记录恰好一个 `span="rag"` 的 `SpanEvent`，`meta` 含 `tool`、`query`、
`knowledge_base_ids`、`hit_count`、`hits`（`rank`、`source_id`、`title`、`score`、
`text_preview`）；`read_document` 额外记录 `offset`、`max_chunks`、`truncated`。
失败时 `status="error"` 且 `error` 为异常文本，并向上抛出。
