# auth-facade

管理员／游客鉴权业务模块。集中处理业务权限和公开知识库范围，通过 auth-runtime 验证身份与管理员证明。对外只提供 AuthService；不导入 agent-facade、rag-facade、data-facade 或其叶子模块。

模块由 Cython 构建为目标平台 `.pyd`／`.so`，集成应用从 `artifacts/` 加载。
