# observability - 接口契约

## observability
```python
class Span:   # async context manager，记�?trace_id/span/耗时
    def __init__(self, ctx, name: str): ...
class TraceStore:
    def record(self, span: SpanEvent) -> None: ...
    def get(self, trace_id: str) -> list[SpanEvent]: ...
```

