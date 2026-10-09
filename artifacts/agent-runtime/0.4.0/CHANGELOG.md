# Changelog

## [0.4.0]
- 接收共享 MemoryStorePort、LLMProviderPort、TraceStorePort，不再导入数据库域实现。
- 新增按用户和会话隔离的 history(ctx)，返回消息及其嵌套工具参数的深拷贝。

## [0.3.3]
- 已选择知识库时，每个问题都必须至少完成一次知识库检索：模型在未检索的情况下想直接收尾时，`run()` 会把它打回并追加 `RETRIEVAL_REQUIRED_MESSAGE`，最多提醒 `MAX_RETRIEVAL_REMINDERS` 次。
- 每次拦截记录一个 `retrieval_guard` span（`meta` 含 `attempt` 与 `knowledge_base_ids`），便于在 trace 里识别“没检索就作答”的回答。
- 系统提示词收紧：唯一可不检索的情况是没有选择知识库；并禁止在未检索时断言知识库内容、禁止复用历史对话里的 `[n]` 引用。

## [0.3.2]
- 系统提示词改为分级回退策略：`search_knowledge_base` → `hybrid_search_knowledge_base` → `keyword_search_knowledge_base` → `list_knowledge_documents` → `read_knowledge_document`。
- 新增 `RETRIEVAL_TOOL_NAMES`：工具循环每轮只执行一次知识库检索，同一轮里的后续检索调用返回 SKIPPED 提示，非检索工具不受影响。
- 明确要求模型先读结果再决定下一轮换工具或换查询，避免一条消息里并发发出多个检索请求。

## [0.3.1]
- 强化 Agentic RAG 路由：已选择知识库时，事实与定义类问题必须先检索核实。
- 将当前知识库选择状态明确写入系统提示，并要求低质量结果改写查询后再次检索。
- 保留未选择知识库和闲聊、翻译、改写、计算等任务的直接回答分支。

## [0.3.0]
- 将固定的前置 RAG 改为 LLM 自主决策的 Agentic 工具循环。
- 工具循环默认最多 10 轮且不允许配置小于 10，到达上限后强制生成最终回答。
- 工具执行可获取选中知识库、当前消息与会话历史等运行上下文。
- 改为加载相关 Skill 的完整内容，并保留最近 20 轮会话供工具使用。

## [0.2.1]
- 为每次 RAG 检索记录独立 trace span，包含查询、知识库范围、命中来源、分数和短摘要。

## [0.2.0]
- 对话可传入知识库标识列表，RAG 只检索选中的范围。

## [0.1.0]
- 初始化 Agent 编排循环。
