# INTERFACE

- `AgentRuntime.run(ctx, user_input, knowledge_base_ids=None) -> str`
- `AgentRuntime(provider, memory, tools, skills, tracing, max_tool_rounds=10)`
- `make_runtime(provider, memory, tools, skills, tracing, max_tool_rounds=10) -> AgentRuntime`
- `run` 不再预先执行 RAG；LLM 可在至少 10 轮的可配置循环内自主调用已注册工具。
- 当前已选择知识库时，事实、定义和文档内容类问题由系统策略强烈约束为先检索；未选择知识库或非知识型任务仍可直接回答。
- `RETRIEVAL_TOOL_NAMES` 列出五个知识库检索工具；同一条 assistant 消息里第二个及之后的检索调用不执行，改为返回 `SKIPPED_RETRIEVAL_MESSAGE`，让模型先读结果再决定下一轮。非检索类工具在同轮内照常按顺序执行。
