# Observability module

The `observability` package provides the in-memory trace store and synchronous/asynchronous span context managers used by the agent service.

Public facade:

- `TraceStore.record(span: SpanEvent) -> None`
- `TraceStore.get(trace_id: str) -> list[SpanEvent]`
- `Span(ctx, name, store=None)` is a synchronous context manager.
- `ASpan(ctx, name, store=None)` is its asynchronous counterpart.
- `make_trace_store() -> TraceStore` creates the default in-memory store.

The canonical parameter and return specifications are maintained in [`specifications/API_SCHEMA.json`](../../specifications/API_SCHEMA.json); this module directory is a Python package inside the root repository, not a separate Git repository. Jenkins compiles its process module with Cython for the Linux `.so` release.
