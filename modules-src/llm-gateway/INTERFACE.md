# INTERFACE

- `LLMProvider.generate(ctx, messages, tools) -> (content, list[ToolCall])`
- `LLMProvider.stream(ctx, messages, tools) -> AsyncIterator[str]`
- `MockProvider(scenario)` / `DeepSeekProvider(api_key, base_url, model, transport=None)`。

## 0.1.2 错误契约

失败抛共享ModelRequestError，code/status_code/message稳定且脱敏；限流429、不可用503、无效响应502、超时504。不直接暴露HTTP请求/凭据或上游正文。
