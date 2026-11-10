# INTERFACE

- `@tool(name, description, parameters, context_aware=False)`：注册到默认 registry，旧的三参数调用保持兼容。
- `ToolRegistry.register(t: ToolDef, fn, context_aware=False) -> None`：注册普通工具或上下文感知工具。
- `ToolRegistry.list(ctx=None) -> list[ToolDef]`：列出公开工具定义；运行上下文不会出现在参数 schema 中。
- `ToolRegistry.execute(ctx, call: ToolCall, runtime_context=None) -> str`：执行工具并将失败转换为 `ERROR:` 字符串。

当 `context_aware=True` 时，handler 除公开业务参数外，还会收到仅限运行时注入的关键字参数 `ctx` 和 `runtime_context`。调用中的同名参数会被可信运行时值覆盖。普通工具只收到 `ToolCall.arguments`，行为与 0.1.0 相同。
