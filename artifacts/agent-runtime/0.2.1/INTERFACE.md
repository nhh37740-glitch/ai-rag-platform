# INTERFACE

- `AgentRuntime.run(ctx, user_input, knowledge_base_ids=None) -> str`
- `make_runtime(provider, vector_store, memory, tools, skills, tracing, kb_scope) -> AgentRuntime`
- `run` 会向 `TraceStore` 记录 `rag` span，其元数据包含查询、检索范围、命中数及来源排名。
