# AuthService 接口规范 0.1.0

本包仅依赖 core_specifications 和标准库。运行阶段交付 Cython .pyd/.so。

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

两项配置均空表示仅游客模式。代理证明至少32 UTF-8字节，owner 必须非空且无首尾空白/控制字符；部分配置或非法配置为 ValueError。
authenticate_proxy 只接受已配置代理证明、固定 owner、admin 角色，否则 PermissionError。管理员 proof 使用本实例随机密钥生成，不同实例不能复用。
游客 role=guest，proof 为空。有效游客和管理员允许 read/query；create_notebook/import_document/write 只允许本实例认证的管理员。未知权限为 ValueError，伪造身份或越权为 PermissionError。
allowed_notebooks 按 available_ids 的顺序去重；游客取与 public_ids 的交集，管理员可读全部 available_ids。返回独立列表。
笔记本 ID 必须为非空单一标识符：首字符为 Unicode 字母、数字或下划线，后续可包括字母、数字、下划线、点、连字符。空白、路径分隔符、控制字符、点路径均拒绝。
错误和 repr 不输出 proof/token。HTTP 层必须只序列化 user_id 和 role；不得直接 dataclasses.asdict(principal)，也不得记录 proof。
