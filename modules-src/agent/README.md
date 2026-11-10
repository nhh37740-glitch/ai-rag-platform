# agent — 智能体业务域

负责一次问答/任务从模型调用、工具执行到结果汇总的编排。读者入口是
`agent-facade/INTERFACE.md`；集成侧只通过 `AgentService` 调用本域。

| 模块 | 职责 |
|---|---|
| `agent-facade` | 本域唯一公开门面：模型选择、问答、工具/技能装配 |
| `agent-runtime` | 智能体循环、上下文与工具调用状态机 |
| `llm-gateway` | OpenAI 兼容模型调用与错误归一化 |
| `skill-runtime` | Skill 加载与执行边界 |
| `tool-runtime` | 工具注册、参数校验与执行 |
| `mcp-gateway` | MCP 客户端网关 |
| `mcp-servers` | 内置 MCP server 实现 |
| `evaluation` | 检索/问答评测辅助 |

允许依赖：本域模块、`core_specifications`、`platform/observability`。
不得反向依赖 `rag/`、`data/`、`auth/` 的具体实现；跨域服务通过注入的 Protocol 使用。
