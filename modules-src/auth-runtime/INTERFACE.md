# AuthRuntime 接口规范 0.4.0

本包仅依赖 core_specifications 和标准库。运行阶段交付 Cython .pyd/.so。

```python
class AuthRuntime:
    def __init__(self, proxy_token: str = "", owner_id: str = ""): ...
    def guest(self, ctx: RequestContext) -> AuthPrincipal: ...
    def authenticate_proxy(self, ctx: RequestContext, proxy_token: str,
                           user_id: str, role: str) -> AuthPrincipal: ...
    def is_authenticated(self, ctx: RequestContext, principal: AuthPrincipal) -> bool: ...
    def is_administrator(self, ctx: RequestContext, principal: AuthPrincipal) -> bool: ...
```

两项配置均空表示仅游客模式。代理证明至少32 UTF-8字节，owner 必须非空且无首尾空白/控制字符；部分配置或非法配置为 ValueError。
authenticate_proxy 要求有效代理证明；admin 仅接受固定 owner，user 接受其它可信登录身份。proof 绑定用户及角色，使用本实例随机密钥生成，不同实例不能复用。
游客 role=guest，proof 为空。`is_administrator` 校验 principal 是否由本实例签发并返回管理员身份；操作权限和可见笔记本规则由 auth-facade 负责。
错误和 repr 不输出 proof/token。HTTP 层必须只序列化 user_id 和 role；不得直接 dataclasses.asdict(principal)，也不得记录 proof。

本次接口扩展以根目录 `specifications/AUTH_INTERFACES.md` 的2026-10-11条款为正式依据。
