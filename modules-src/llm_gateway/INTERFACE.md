# INTERFACE

- `LLMProvider.generate(ctx, messages, tools) -> (content, list[ToolCall])`
- `LLMProvider.stream(ctx, messages, tools) -> AsyncIterator[str]`
- `MockProvider(scenario)` / `DeepSeekProvider(api_key, base_url, model)`。
