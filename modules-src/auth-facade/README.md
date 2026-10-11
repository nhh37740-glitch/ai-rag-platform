# auth-facade

管理员／成员／游客鉴权业务模块。通过 auth-runtime 验证可信身份；AuthService 管理持久笔记本成员和 viewer/editor/manager 权限，DailyQueryQuota 管理全站查询额度。通过共享 NotebookStorePort 注入成员关系；额度使用 StateStorePort；不导入 agent-facade、rag-facade、data-facade 或其叶子模块。

模块由 Cython 构建为目标平台 `.pyd`／`.so`，集成应用从 `artifacts/` 加载。

笔记本目录与角色/权限来自关系表；manager可管理成员和改名，全局管理员另可归档/恢复；公开目录只读，归档目录禁止问答。成员必须已登记可信用户，写操作版本冲突后重新授权，不能恢复已撤销权限。正式矩阵见 docs/NOTEBOOK_PERMISSIONS.md。
