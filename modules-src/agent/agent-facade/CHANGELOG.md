## 0.5.2 - 2026-10-13

## 0.5.3 — 2026-10-13

- 免费模型目录要求文本输入输出与工具调用能力；保留用户选定模型，不静默回退。

- Restore administrator file creation and conversation-to-notebook tools through AgentService.

## 0.5.1 - 2026-10-13

- Accept persisted conversation history and disable all memory reads/writes for guest requests.

# agent-facade

## 0.4.0 — 2026-10-11

- 增加 Provider/Model 目录和管理员选择接口，凭据只从服务器环境读取。
- 模型选择写入统一 agent_data，启动恢复；切换后新请求使用新 Runtime。
- Provider 更新串行提交并原子替换 Runtime，正在运行的问答继续使用开始时的配置。

## 0.3.0 — 2026-10-11

将既有环境模型配置及OpenRouter免费选择策略归入resolve_model_config业务接口；返回隐藏凭据repr的不可变共享值对象。管理员目录管理仍为设计。

# Changelog

## [0.1.0]
- 将 AgentRuntime、工具注册、技能加载与 Provider 选择集中为 AGENT 中间包。
- 数据和检索使用共享接口注入；五个保留 RAG 工具只接受当前运行范围。
- 公开额外工具注册、用户/会话历史副本和幂等关闭；不关闭外部注入资源。

## 0.2.0 — 2026-10-11

- 传递单次运行的写工具授权，兼容默认参数。

## 0.5.0 — 2026-10-12

- 支持按请求临时选择当前活动 Provider 下的模型，不改变管理员的全局选择。
- 游客运行时由调用方限制在只读问答；模型目录校验与 Provider 绑定在 AgentService。
