# rag-skill Interface

版本：0.1.0

```python
class RagSkill:
    def __init__(self, store: VectorStore, tracing: TraceStore, top_k: int = 5): ...
    def tool_definition(self) -> ToolDef: ...
    def execute(
        self,
        ctx: RequestContext,
        query: str,
        knowledge_base_ids: list[str],
        top_k: int | None = None,
    ) -> str: ...
```

`tool_definition()` 返回 `search_knowledge_base`，仅向 LLM 暴露必填的 `query` 和可选的
`top_k`（1–20）。`knowledge_base_ids` 始终由调用方根据当前请求注入。

返回值是 UTF-8 JSON 字符串，包含 `query`、`hit_count` 和 `citations`。每次调用记录
`span="rag"` 的 `SpanEvent`；事件包含范围、命中来源、得分及文本短摘要。
