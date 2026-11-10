# auth-facade

`AuthService` 管理 RAGnotebook 账号注册登录、进程内会话校验、项目管理员操作、笔记本成员权限和全站每日额度。它依赖 `auth-runtime` 和公开的数据服务接口。

项目管理员由 `users.is_admin` 表示；笔记本所有者由 `notebooks.owner_user_id` 表示。成员角色只有 `editor`、`viewer`。游客可作为 viewer 被共享；游客聊天历史不在此模块保存。
