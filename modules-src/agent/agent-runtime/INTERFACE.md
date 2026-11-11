# INTERFACE

版本：0.6.0。provider、memory、tracing 分别接收共享 LLMProviderPort、MemoryStorePort、TraceStorePort。

- `AgentRuntime.history(ctx: RequestContext) -> list[ChatMessage]` 返回按 user_id/session_id 隔离的深拷贝快照。

- `AgentRuntime.run(ctx, user_input, knowledge_base_ids=None) -> str`
- `AgentRuntime(provider, memory, tools, skills, tracing, max_tool_rounds=10)`
- `make_runtime(provider, memory, tools, skills, tracing, max_tool_rounds=10) -> AgentRuntime`
- `run` 不再预先执行 RAG；LLM 可在至少 10 轮的可配置循环内自主调用已注册工具。
- 当前已选择知识库时，每个问题都必须至少检索一次；模型未检索就想收尾时会被打回，并追加 `RETRIEVAL_REQUIRED_MESSAGE`，最多 `MAX_RETRIEVAL_REMINDERS` 次。只有未选择知识库时才允许直接回答。
- 每次拦截记录一个 `retrieval_guard` span，`meta` 含 `attempt`（第几次提醒）、`reason` 与 `knowledge_base_ids`。
- `RETRIEVAL_TOOL_NAMES` 列出五个知识库检索工具；同一条 assistant 消息里第二个及之后的检索调用不执行，改为返回 `SKIPPED_RETRIEVAL_MESSAGE`，让模型先读结果再决定下一轮。非检索类工具在同轮内照常按顺序执行。
- 相同工具 + 相同参数重复查询不再执行，返回 `DUPLICATE_RETRIEVAL_MESSAGE`，并记录 `reason=duplicate_query` 的 `retrieval_guard` span。
- 检索结果可解析为 JSON 且全部 `hit_count=0` 时，最终回答替换为 `NO_EVIDENCE_ANSWER`，避免把模型常识或历史引用伪装成知识库结论。非 JSON 的自定义工具结果视为“证据状态未知”，不误判为空命中。
- 每次结束记录 `agent_stop` span，`meta.stop_reason` 为 `answered_with_evidence`、`answered`、`no_evidence`、`retrieval_required_not_met` 或 `max_tool_rounds`，并带 `retrieval_calls`。

本次接口扩展以根目录 `specifications/DOMAIN_INTERFACES.md` 的2026-10-11条款为正式依据。

run 支持 history 快照和 memory_enabled=False；后者既不读写记忆，也不保留游客进程内历史。
