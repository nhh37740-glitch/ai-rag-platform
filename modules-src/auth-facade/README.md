# auth-facade

管理员／成员／游客鉴权业务模块。通过 auth-runtime 验证可信身份；AuthService 管理持久笔记本成员和 viewer/editor/manager 权限，DailyQueryQuota 管理全站查询额度。通过共享 StateStorePort 注入状态；不导入 agent-facade、rag-facade、data-facade 或其叶子模块。

模块由 Cython 构建为目标平台 `.pyd`／`.so`，集成应用从 `artifacts/` 加载。
