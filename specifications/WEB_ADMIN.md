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
