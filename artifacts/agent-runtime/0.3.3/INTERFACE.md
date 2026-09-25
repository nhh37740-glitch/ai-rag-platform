# INTERFACE

- `AgentRuntime.run(ctx, user_input, knowledge_base_ids=None) -> str`
- `AgentRuntime(provider, memory, tools, skills, tracing, max_tool_rounds=10)`
- `make_runtime(provider, memory, tools, skills, tracing, max_tool_rounds=10) -> AgentRuntime`
- `run` 不再预先执行 RAG；LLM 可在至少 10 轮的可配置循环内自主调用已注册工具。
- 当前已选择知识库时，每个问题都必须至少检索一次；模型未检索就想收尾时会被打回，并追加 `RETRIEVAL_REQUIRED_MESSAGE`，最多 `MAX_RETRIEVAL_REMINDERS` 次。只有未选择知识库时才允许直接回答。
- 每次拦截记录一个 `retrieval_guard` span，`meta` 含 `attempt`（第几次提醒）与 `knowledge_base_ids`。
- `RETRIEVAL_TOOL_NAMES` 列出五个知识库检索工具；同一条 assistant 消息里第二个及之后的检索调用不执行，改为返回 `SKIPPED_RETRIEVAL_MESSAGE`，让模型先读结果再决定下一轮。非检索类工具在同轮内照常按顺序执行。
