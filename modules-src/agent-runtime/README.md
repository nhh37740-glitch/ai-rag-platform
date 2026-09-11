# agent_runtime

最薄 Agentic 编排循环，负责串联记忆、完整 Skill、会话历史、LLM 与工具。RAG 不再固定前置，而是与文件创建、对话入库一样由 LLM 按需调用；循环默认最多 10 轮。
