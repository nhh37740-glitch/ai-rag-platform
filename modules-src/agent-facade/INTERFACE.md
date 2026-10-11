# AGENT 接口规范 0.4.0

唯一共享类型来自 core_specifications。完整签名登记在 API_SCHEMA.json。

```python
def make_provider(api_key: str = "", base_url: str = "https://api.deepseek.com",
                  model: str = "deepseek-chat", scenario: str = "qa") -> LLMProviderPort: ...
class AgentService:
    def __init__(self, data: DataServicePort, rag: RagServicePort, tracing: TraceStorePort | None = None,
                 skill_dir: str = "", provider: LLMProviderPort | None = None,
                 max_tool_rounds: int = 10, environment: dict[str, str] | None = None): ...
    async def run(self, ctx: RequestContext, user_input: str,
                  knowledge_base_ids: list[str] | None = None, allow_write_tools: bool = True) -> str: ...
    def register_tool(self, ctx: RequestContext, definition: ToolDef,
                      handler: Callable, context_aware: bool = False) -> None: ...
    def tool_definitions(self, ctx: RequestContext) -> list[ToolDef]: ...
    def history(self, ctx: RequestContext) -> list[ChatMessage]: ...
    async def aclose(self, ctx: RequestContext) -> None: ...
```

provider 是只读属性，保留注入对象身份供请求级核查。空 key 使用 Mock；非空 key 使用 DeepSeek。
创建时自动注册全部五个 RAG 工具，禁止额外工具覆盖它们。模型参数不能覆盖 ctx、runtime_context 或知识库范围。
工具定义和 history 均返回深拷贝。history 按 user_id/session_id 隔离。
run 拒绝空白输入；max_tool_rounds 至少为10。关闭幂等，关闭后 run/register_tool/tool_definitions/history 抛 RuntimeError。
未传 tracing 时使用 RagService 提供的追踪接口；关闭只释放 AgentRuntime，不关闭注入的 data/rag/provider/tracing。
保留 AgentRuntime 当前有限次检索提醒策略；严格检索成功保证和引用校验不属于本次接口重构。

本次接口扩展以根目录 `specifications/DOMAIN_INTERFACES.md` 的2026-10-11条款为正式依据。

0.3.0提供 resolve_model_config(ctx,environment,public=False)->ModelConfiguration，负责既有环境配置选择、免费模型ID校验、固定OpenRouter地址及凭据配置错误处理。api_key仅在服务器内存使用，repr隐藏，HTTP不得序列化整个对象。


## Provider / Model 管理（0.4.0）

AgentService 可选接收末尾参数 environment（服务端环境副本），旧构造调用兼容；凭据只从该副本读取。

方法签名：

- list_model_providers(ctx: RequestContext, environment: dict[str, str]) -> list[dict]
- list_models(ctx: RequestContext, provider_id: str, environment: dict[str, str]) -> list[dict]
- get_model_settings(ctx: RequestContext) -> dict
- update_model_settings(ctx: RequestContext, provider_id: str, model_id: str) -> dict
AgentService 提供 list_model_providers(ctx, environment)、list_models(ctx, provider_id, environment)、get_model_settings(ctx)、update_model_settings(ctx, provider_id, model_id)。Provider 凭据仅从服务器环境读取，所有响应只包含配置状态，不含凭据。OpenRouter 目录读取当前上游模型目录，只返回标记免费或输入/输出价格均为零的模型；可用 OPENROUTER_MODELS(JSON数组) 提供当前目录快照。未知 Provider、无凭据 Provider 和非免费模型均拒绝。

当前选择以 agent_data 的 (type='model_settings', name='active') 持久化。启动时恢复选择并从服务器环境重新取凭据。update 先校验目录与凭据，再写入 agent_data，随后替换 AgentRuntime；已开始的请求继续使用其开始时的 Runtime，新请求看到切换后的 Provider。并发更新由单一锁串行化。模型管理接口的管理员权限由 HTTP 路由鉴权。
