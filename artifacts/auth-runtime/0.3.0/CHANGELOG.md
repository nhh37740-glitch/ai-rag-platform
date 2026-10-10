# Changelog

## [0.3.0]
- Move permission and notebook visibility policies into auth-facade.
- Rename the low-level entrypoint to AuthRuntime.

## [0.2.0]
- Add verified-principal role inspection for auth-facade.
- Keep existing policy entrypoints during the compatibility migration.

## [0.1.0]
- 独立公共鉴权模块，通过共享 AuthPrincipal 定义游客和管理员权限。
- 固定代理证明、owner 和 admin 角色认证；代理证明用恒定时间比较。
- 管理员身份使用本实例随机密钥签发的 HMAC proof，拒绝角色伪造和跨实例证明。
- 游客仅 read/query，笔记本范围固定为服务端公开范围交集。
- 统一不含凭据的错误及 repr，不进行日志、trace 或网络访问。
- Cython 关闭参数与元素类型推断，非法输入在源码及二进制中保持相同校验与错误类型。
