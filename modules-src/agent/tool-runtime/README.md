# tool_runtime

Agent 工具注册与执行模块。`ToolRegistry` 保存面向 LLM 的 `ToolDef`，统一分发 `ToolCall`，并将工具异常转换成可返回给 LLM 的错误字符串。

普通工具只接收公开业务参数。需要访问请求身份、已选知识库或其他可信运行状态的工具，可使用 `context_aware=True` 注册：

```python
registry.register(tool_def, search_knowledge_base, context_aware=True)
result = registry.execute(ctx, call, runtime_context={"knowledge_base_ids": ["kb-a"]})
```

上下文感知 handler 通过仅限运行时的关键字参数 `ctx` 和 `runtime_context` 接收这些值；它们不需要、也不应写入向 LLM 暴露的 JSON Schema。`@tool(...)` 装饰器同样支持 `context_aware=True`，原有三参数用法保持兼容。
