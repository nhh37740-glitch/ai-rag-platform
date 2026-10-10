# auth-runtime

公共鉴权运行时模块，仅提供游客身份创建、可信代理身份认证及管理员证明验证原语。管理员／游客的业务权限和知识库可见范围由独立的 `auth-facade` 承载。身份类型和端口来自 core_specifications。

应用负责从可信内部代理取 proof/owner/role，再调用 authenticate_proxy；请求 JSON 的 role/user_id 不能授予管理员权限。
管理员身份 proof 仅在进程内部传递，HTTP 响应必须只输出 user_id/role。接口详情见 INTERFACE.md。

源码单测由根目录 scripts/run_tests.py 的 leaf 分组收集；集成运行必须加载 artifacts 当前平台编译产物。
