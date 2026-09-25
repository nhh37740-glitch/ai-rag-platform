# INTERFACE

- `AgentRuntime.run(ctx, user_input, knowledge_base_ids=None) -> str`
- `AgentRuntime(provider, memory, tools, skills, tracing, max_tool_rounds=10)`
- `make_runtime(provider, memory, tools, skills, tracing, max_tool_rounds=10) -> AgentRuntime`
- `run` 不再预先执行 RAG；LLM 可在至少 10 轮的可配置循环内自主调用已注册工具。
