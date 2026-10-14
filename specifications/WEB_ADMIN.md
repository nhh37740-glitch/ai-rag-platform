# RAGnotebook 浏览器 HTTP 契约

浏览器只与 `RAGnotebook` HTTP API 交互。RAGnotebook 是唯一后端入口和唯一后端进程；`auth-facade`、`data-facade`、`rag-facade`、`agent-facade` 在进程内运行，不单独开放网络端口。HTTP 路由不直接访问关系数据库、向量库或其他一级能力模块。

| 浏览器功能 | HTTP 接口 | 业务模块 |
| --- | --- | --- |
| 注册、登录、登出、身份查询 | `/api/auth/register`、`/api/auth/login`、`/api/auth/logout`、`/api/auth/session` | `auth-facade` |
| 管理账号 | `/api/admin/users` | `auth-facade` |
| 查询共享对象、设置或撤销成员 | `/api/notebooks/{id}/share-targets`、`/members/{user_id}` | `auth-facade`、`data-facade` |
| 笔记本列表与创建 | `/api/notebooks` | `auth-facade`、`data-facade` |
| 查看和上传文档 | `/api/notebooks/{id}/documents`、`/files` | `auth-facade`、`data-facade`、`rag-facade` |
| 问答与会话历史 | `/api/chat`、`/api/conversations` | `auth-facade`、`data-facade`、`rag-facade`、`agent-facade` |
| 管理员查询/切换 Provider 与 Model；游客查询当前 Provider 模型并为单次问答选择 Model | `/api/models/providers`、`/api/models/{provider_id}`、`/api/models/settings`、`/api/models/guest`、`/api/chat` | `auth-facade`、`agent-facade`、`data-facade` |
| 查询追踪 | `/api/trace/{trace_id}` | `auth-facade`、`rag-facade` |

会话重启后需要重新登录。每个请求重新检查账号有效状态。游客可查看或问答共享给游客的笔记本；游客聊天不保存。模型密钥只从服务器配置读取，API 不返回密钥。管理员决定活动 Provider；游客只能从 `/api/models/guest` 返回的活动 Provider 目录中选择模型，选择仅用于当前问答，不覆盖管理员默认设置。`/api/llm/config` 和问答响应返回全站共享额度；游客可见的剩余次数与其他用户共用。

游客问答可附带 `model_id` 与目录中的 `catalog_provider_id`；服务端再次核对当前 Provider 和模型目录，目录已切换时返回 409。注册用户和管理员不能指定此临时覆盖；任何问答请求都不能直接指定 provider_id。

数据结构和模块接口见 [`DOMAIN_INTERFACES.md`](DOMAIN_INTERFACES.md) 与 [`AUTH_INTERFACES.md`](AUTH_INTERFACES.md)。

## RAGnotebook 0.9.1 导入任务

POST /api/notebooks/{id}/files 的可选 background=true 在文件校验/暂存后返回202 `{notebook_id, upload_id, state}`；默认同步模式保持201完整回执。全站最多一个导入任务，忙时409。GET /api/uploads/{upload_id} 保持身份与笔记本写权限检查：state=running/error/done；done时result为原完整回执（含imported字节/字符/块数/sha256/source_id），error时message为失败原因。前端通过短请求轮询终态，不把请求传输完成或临时网络失败当作导入完成；重启丢失进程内任务记录时提示检查来源后再操作，不静默重复上传。

网页本地恢复记录按user_id隔离，仅含notebookId/uploadId。登录与页面刷新后仍通过受权限保护的GET进度续看；终态清理记录，不自动重发文件。
