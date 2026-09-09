# agent-runtime - 接口契约

## agent_runtime
```python
class AgentRuntime:
    def __init__(self, provider, rag, memory, tools, skills, tracing): ...
    async def run(self, ctx, user_input: str) -> str: ...   # 理解→记忆→Skill→RAG/Tool→LLM→执行→再LLM→写记忆
```

