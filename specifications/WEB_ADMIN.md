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
| Provider/Model 查询和管理员切换 | `/api/models/providers`、`/api/models/{provider_id}`、`/api/models/settings` | `auth-facade`、`agent-facade`、`data-facade` |
| 查询追踪 | `/api/trace/{trace_id}` | `auth-facade`、`rag-facade` |

会话重启后需要重新登录。每个请求重新检查账号有效状态。游客可查看或问答共享给游客的笔记本；游客聊天不保存。模型密钥只从服务器配置读取，API 不返回密钥。

数据结构和模块接口见 [`DOMAIN_INTERFACES.md`](DOMAIN_INTERFACES.md) 与 [`AUTH_INTERFACES.md`](AUTH_INTERFACES.md)。
