# agent_runtime

最薄 Agentic 编排循环，负责串联记忆、完整 Skill、会话历史、LLM 与工具。当前已选择知识库时，**每个问题都必须至少检索一次**：模型若想不检索直接回答，会被打回重来（最多 `MAX_RETRIEVAL_REMINDERS` 次）并记一条 `retrieval_guard` span；只有没有选择知识库时才允许直接回答。检索失败时按 `search_knowledge_base` → `hybrid_search_knowledge_base` → `keyword_search_knowledge_base` → `list_knowledge_documents` → `read_knowledge_document` 逐级回退，并且每轮只执行一次知识库检索，先读结果再决定下一步。文件创建和对话入库由 LLM 按用户明确请求调用，工具循环默认最多 10 轮。
