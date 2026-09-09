# INTERFACE

- `@tool(name, description, parameters)` 装饰器（注册到默认 registry）。
- `ToolRegistry.register(t: ToolDef, fn)` / `list(ctx)` / `execute(ctx, call: ToolCall) -> str`.
