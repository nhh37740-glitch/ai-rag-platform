# llm_gateway

统一 `LLMProvider.generate/stream` 接口；`MockProvider`（离线）与 `DeepSeekProvider`（OpenAI 兼容，deepseek-chat 函数调用）。

上游失败统一转为脱敏的 `ModelRequestError`，区分鉴权、额度、模型不存在、请求拒绝、限流、超时、连接失败和无效响应，见 `INTERFACE.md`。
