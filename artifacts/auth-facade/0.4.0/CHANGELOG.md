# auth-facade

## 0.4.0 — 2026-10-11

成员授权改用NotebookStorePort关系表；按资源角色权限决策，事务版本冲突后重新授权；新增manage_notebook及管理员归档/恢复权限，保留全站20次策略。

# Changelog

## [0.2.0]
- Add site-wide DailyQueryQuota policy with Beijing-midnight reset and injected atomic persistence.

## [0.1.0]
- Extract guest/admin permission and notebook visibility policy into auth-facade.
- Delegate identity and proxy-proof validation to auth-runtime.

## 0.3.0 — 2026-10-11

- 新增持久笔记本成员角色、权限检查和增改删；普通用户范围由成员策略授权。
