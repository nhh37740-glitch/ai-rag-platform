# agent_runtime

最薄 Agent 编排循环，负责串联记忆/Skill/按所选知库检索/Tool/LLM，不包含任何子模块实现。RAG 阶段会记录独立 trace span，便于核对检索范围和命中来源。
