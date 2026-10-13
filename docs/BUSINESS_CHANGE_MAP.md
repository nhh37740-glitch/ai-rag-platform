# RAG 业务模块变更归属

任务：RAG-NOTEBOOK-20261011；日期：2026-10-11（北京时间）。本表按当前 RAGnotebook 重构方案生效。

| 功能 | 业务模块 | 功能结果 |
| --- | --- | --- |
| 浏览器 HTTP 接口与网页 | `RAGnotebook` | 唯一浏览器入口和唯一后端进程；HTTP 路由只使用四个业务模块的公开接口。 |
| 注册、登录、账号禁用、笔记本权限、全站额度 | `auth-facade` | 本地账号、进程内会话、即时有效状态检查；所有身份共用每日 100 次额度。 |
| 关系数据、会话、记忆、模型配置及向量存储 | `data-facade` | 单个 SQLite 文件、六张固定表；统一提供读写接口。 |
| 文档解析、切分、嵌入、入库、检索和 RAG 追踪 | `rag-facade` | `RAGnotebook` 经 `RagService` 完成上传和检索，不直接访问能力模块。 |
| Agent 问答和 Provider/Model 管理 | `agent-facade` | 管理员切换服务端已配置模型；密钥不返回浏览器。 |

笔记本所有者保存在 `notebooks.owner_user_id`，不是项目管理员或成员角色。成员角色仅 `editor`、`viewer`；游客可以 `viewer` 身份被分享，游客会话不保存。关系表和接口见 `specifications/DOMAIN_INTERFACES.md`、`specifications/AUTH_INTERFACES.md`。
