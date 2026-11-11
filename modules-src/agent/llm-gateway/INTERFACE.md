# INTERFACE

- `LLMProvider.generate(ctx, messages, tools) -> (content, list[ToolCall])`
- `LLMProvider.stream(ctx, messages, tools) -> AsyncIterator[str]`
- `MockProvider(scenario)` / `DeepSeekProvider(api_key, base_url, model, transport=None)`。

## 0.2.0 错误契约

失败抛共享 `ModelRequestError`，`code`/`status_code`/`message` 稳定且脱敏；不直接暴露 HTTP 请求、凭据或上游正文。

| HTTP | code | status_code |
|---|---|---|
| 401/403 | `model_auth_failed` | 502 |
| 402 | `model_quota_exhausted` | 502 |
| 404 | `model_not_found` | 502 |
| 400/422 | `model_request_rejected` | 502 |
| 429 | `model_rate_limited` | 429 |
| 5xx/其它失败 | `model_unavailable` | 503 |
| 超时 | `model_timeout` | 504 |
| 连接失败 | `model_connection_failed` | 503 |
| 200 但内容无效 | `model_invalid_response` | 502 |
