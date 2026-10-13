# Provider 与 Model 管理

适用：RAGnotebook 单进程、单 SQLite 数据库重构。本文件取代旧的多表与每日 20 次额度设计。

## 业务边界

浏览器只访问 RAGnotebook HTTP API。HTTP 只调用 agent-facade 的 AgentService 公开方法，不访问 Provider SDK、密钥配置或 agent_data。Provider 凭据只从服务器环境读取，不能存入数据库、日志或返回浏览器。模型选择由 agent-facade 管理，并经 data-facade 写入同一 SQLite 文件的 agent_data 表。

## AgentService 接口

- list_model_providers(ctx, environment) -> list[dict]：列出支持的 Provider 和凭据配置状态。
- list_models(ctx, provider_id, environment) -> list[dict]：列出该 Provider 当前可选模型。
- get_model_settings(ctx) -> dict：读取当前 Provider/Model 选择。
- update_model_settings(ctx, provider_id, model_id) -> dict：检查管理员权限及模型有效性后持久化选择。
- run(ctx, ...) 每次读取已保存的选择；管理员变更后，后续问答使用新配置。

API 凭据状态只能返回是否已配置，不能返回凭据内容。

## 数据与额度

仅使用既定六张表。模型选择放入 agent_data，不增加关系表。用户、游客、管理员共享每日 100 次额度，按北京时间日期计数；auth-facade 调用 data-facade 原子预占，每次问答还要检查账号有效状态。

管理员可以查看 Provider、Model 并切换全站选择；普通用户不能修改。当前运行中的问答可继续使用启动该次问答时解析的配置。

## 验收

确认接口能列出 Provider/Model；管理员修改后后续问答使用新模型；普通用户越权修改会被拒绝；响应、数据库、日志不含密钥；模型选择复用 agent_data，不建第七张表；三类用户共享且不超过每日 100 次。
