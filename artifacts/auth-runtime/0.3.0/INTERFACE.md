# AuthRuntime 接口规范 0.3.0

本包仅依赖 core_specifications 和标准库。运行阶段交付 Cython .pyd/.so。

```python
class AuthRuntime:
    def __init__(self, proxy_token: str = "", owner_id: str = ""): ...
    def guest(self, ctx: RequestContext) -> AuthPrincipal: ...
    def authenticate_proxy(self, ctx: RequestContext, proxy_token: str,
                           user_id: str, role: str) -> AuthPrincipal: ...
    def is_administrator(self, ctx: RequestContext, principal: AuthPrincipal) -> bool: ...
```

两项配置均空表示仅游客模式。代理证明至少32 UTF-8字节，owner 必须非空且无首尾空白/控制字符；部分配置或非法配置为 ValueError。
authenticate_proxy 只接受已配置代理证明、固定 owner、admin 角色，否则 PermissionError。管理员 proof 使用本实例随机密钥生成，不同实例不能复用。
游客 role=guest，proof 为空。`is_administrator` 校验 principal 是否由本实例签发并返回管理员身份；操作权限和可见笔记本规则由 auth-facade 负责。
错误和 repr 不输出 proof/token。HTTP 层必须只序列化 user_id 和 role；不得直接 dataclasses.asdict(principal)，也不得记录 proof。
