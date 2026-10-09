# AGENT 接口规范 0.1.0

唯一共享类型来自 core_specifications。完整签名登记在 API_SCHEMA.json。

```python
def make_provider(api_key: str = "", base_url: str = "https://api.deepseek.com",
                  model: str = "deepseek-chat", scenario: str = "qa") -> LLMProviderPort: ...
class AgentService:
    def __init__(self, data: DataServicePort, rag: RagServicePort, tracing: TraceStorePort,
                 skill_dir: str = "", provider: LLMProviderPort | None = None,
                 max_tool_rounds: int = 10): ...
    async def run(self, ctx: RequestContext, user_input: str,
                  knowledge_base_ids: list[str] | None = None) -> str: ...
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
关闭仅释放本包自建的内存运行对象，不关闭注入的 data/rag/provider/tracing。
保留 AgentRuntime 当前有限次检索提醒策略；严格检索成功保证和引用校验不属于本次接口重构。
