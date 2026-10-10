# 鉴权业务接口规范 0.2.0

`auth-facade` 承载管理员／游客的业务权限和知识库可见范围；身份与代理证明的底层校验交由 `auth-runtime`。本模块只依赖共享类型及 auth-runtime，不依赖 Agent、RAG 或数据业务实现。

```python
class AuthService:
    def __init__(self, proxy_token: str = "", owner_id: str = ""): ...
    def guest(self, ctx: RequestContext) -> AuthPrincipal: ...
    def authenticate_proxy(self, ctx: RequestContext, proxy_token: str,
                           user_id: str, role: str) -> AuthPrincipal: ...
    def authorize(self, ctx: RequestContext, principal: AuthPrincipal,
                  permission: str) -> None: ...
    def allowed_notebooks(self, ctx: RequestContext, principal: AuthPrincipal,
                          available_ids: list[str], public_ids: list[str]) -> list[str]: ...
```

有效游客及管理员可 `read`／`query`；只有管理员可 `create_notebook`／`import_document`／`write`。游客仅可读取 `available_ids` 与 `public_ids` 的交集，管理员可读取全部 `available_ids`。无效 principal 为 PermissionError；未知权限或非法笔记本 ID 为 ValueError。API 层必须从服务端状态取得 principal 和可用 ID，不能采用浏览器提交的角色。

DailyQueryQuota(store: StateStorePort, limit: int = 20) 提供 `status(ctx: RequestContext) -> dict` 和 `reserve(ctx: RequestContext) -> dict`。计数使用服务端固定全站身份与北京时间日期，跨用户共享；通过 StateStorePort.increment_if_below 原子持久化，跨实例一致。reserve 在耗尽时抛 PermissionError，status 返回 scope=site、limit、used、remaining、reset_at；无效计数拒绝，不能重置或透支。此策略仅依赖共享端口，不导入数据模块。
