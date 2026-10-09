# 0.2.1
- 共享接口包迁移为 core_specifications；重新构建二进制并保持本模块接口行为。

# Changelog

## [0.2.0]
- `ToolRegistry.register` 新增可选的 `context_aware` 标记。
- `ToolRegistry.execute` 新增可选的 `runtime_context`，并为上下文感知 handler 注入可信的 `ctx` 与 `runtime_context` 关键字参数。
- `@tool` 装饰器支持上下文感知工具，同时兼容原有调用方式。

## [0.1.0]
- 初始化 Agent 工具注册、列举和执行能力。
