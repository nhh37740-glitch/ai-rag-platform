# auth-runtime

公共鉴权编译模块，统一游客只读/查询与管理员写权限。身份类型和端口来自 core_specifications。

应用负责从可信内部代理取 proof/owner/role，再调用 authenticate_proxy；请求 JSON 的 role/user_id 不能授予管理员权限。
管理员身份 proof 仅在进程内部传递，HTTP 响应必须只输出 user_id/role。接口详情见 INTERFACE.md。

源码单测由根目录 scripts/run_tests.py 的 leaf 分组收集；集成运行必须加载 artifacts 当前平台编译产物。
