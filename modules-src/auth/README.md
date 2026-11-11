# auth — 账号与鉴权业务域

负责账号、登录会话、权限校验和每日额度。读者入口是
`auth-facade/INTERFACE.md`；集成侧只通过 `AuthService` 调用本域。

| 模块 | 职责 |
|---|---|
| `auth-facade` | 本域唯一公开门面：登录、会话、额度与权限 |
| `auth-runtime` | 密码哈希、令牌与鉴权原语 |

允许依赖：`core_specifications` 与标准库。`auth-runtime` 不得依赖任何其他业务模块或第三方包。
