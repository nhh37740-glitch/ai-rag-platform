# llm-gateway - 接口契约

## llm_gateway
```python
class LLMProvider(Protocol):
    async def generate(self, ctx, messages: list[ChatMessage], tools: list[ToolDef] | None = None
                       ) -> tuple[str, list[ToolCall]]: ...        # (answer, tool_calls)
    async def stream(self, ctx, messages: list[ChatMessage], tools: list[ToolDef] | None = None): ...

class DeepSeekProvider:  # httpx，读 DEEPSEEK_API_KEY / DEEPSEEK_BASE_URL / DEEPSEEK_MODEL
    def __init__(self, api_key: str, base_url: str = "https://api.deepseek.com", model: str = "deepseek-chat"): ...

class MockProvider:  # 离线：按预置答案/工具调用规则返回，用于演示与测试
    def __init__(self, scenario: str = "qa"): ...
```

