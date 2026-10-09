# rag-facade 0.1.0

Public export: `RagService`. Shared types come from `core_specifications`.
Canonical signatures and acceptance cases R01–R05 are defined in
`specifications/DOMAIN_INTERFACES.md`; the package schema mirrors the root API schema.

Construct with `RagService(store: VectorStore, tracing: TraceStorePort, top_k: int = 5)`.
The caller owns persistence and tracing. No database connection is created here.
Search modes are vector, hybrid and keyword. Queries must be nonempty; top_k is
an integer 1..20 excluding bool. Scope is always an explicit list; [] yields no
documents. Reads enforce scope and pagination (default 20, maximum 100 chunks).
Citation metadata includes chunk_index and total_chunks; tool JSON additionally
reports offset, truncated and next_offset.

`execute_tool` accepts only the five read-only RagTools tools. Model arguments
`ctx`, `runtime_context` and `knowledge_base_ids` are ignored; unknown remaining
arguments/tools raise ValueError. Typed retrieval and tool execution record rag
spans, including validation failures. Empty-scope search does not load embeddings.

Ingestion supports md/txt/docx/pdf via ingestion. Empty extracted content is
rejected before a title is added. source_id is exactly kb/document, without path
traversal or separators within either component. VectorStore.add determines
atomic replacement semantics. IngestResult reports source_id, knowledge_base_id
and chunk_count. The embedding backend follows rag_core configuration.
