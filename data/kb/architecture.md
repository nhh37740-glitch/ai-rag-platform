# 系统架构

- 服务间通过 REST/OpenAPI 通信。
- 记忆分层：SessionMemory（会话）+ UserMemory（用户）。
- 工具与技能按需加载，经 Function Calling / MCP 暴露。
