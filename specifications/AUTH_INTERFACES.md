# 鉴权接口与验收矩阵

auth-facade/AuthService 0.2.0 是管理员／游客权限业务模块，依赖共享类型和 auth-runtime；auth-runtime/AuthRuntime 负责身份校验与管理员代理证明验证，仅依赖共享类型及标准库。两者都不依赖 Agent、RAG、Data 业务模块。所有身份来自服务端；HTTP 层不能把 JSON role/user_id 直接作为管理员身份。

DailyQueryQuota 通过注入的 StateStorePort 提供全站每日查询额度，默认20次，按北京时间零点重置。跨身份及重启共享持久计数；reserve/status 返回额度摘要，超额 PermissionError 由 HTTP 层转为429。接口详见 modules-src/auth-facade/INTERFACE.md。计数不保存密钥或问题正文。

构造 AuthService(proxy_token: str = "", owner_id: str = "")：两者均空为仅游客模式；部分配置、少于32字节的证明或空白 owner 拒绝（ValueError）。证明只保存于服务端对象，不进入日志或响应。

公开签名固定：

- guest(ctx: RequestContext) -> AuthPrincipal：user_id 使用 ctx 或 guest，role=guest，无管理证明。
- authenticate_proxy(ctx: RequestContext, proxy_token: str, user_id: str, role: str) -> AuthPrincipal：恒定时间验证已配置代理证明、固定 owner、admin 角色；无效为 PermissionError。返回带本实例签发的不可伪造 proof，HTTP 不输出 proof。
- authorize(ctx: RequestContext, principal: AuthPrincipal, permission: str) -> None：read/query 对有效游客及管理员开放；create_notebook/import_document/write 只允许本实例验证的管理员。未知 permission 为 ValueError；伪造角色/证明为 PermissionError。
- allowed_notebooks(ctx: RequestContext, principal: AuthPrincipal, available_ids: List[str], public_ids: List[str]) -> List[str]：管理员可读全部服务端可用范围，游客仅返回公开范围交集，保持顺序并去重。未认证身份拒绝。输入非法 ID 为 ValueError。

验收用例：A01 游客 read/query 成功，三种写操作失败；A02 正确 owner/proxy/admin 身份通过全部权限，错误证明/角色/用户失败；A03 直接构造伪造 AuthPrincipal、复制跨实例证明无法升级权限；A04 游客范围交集、管理员完整范围、非法 ID、未知权限；A05 身份响应及错误/trace 不含 proof/token；A06 公共页面读取文档和自由查询成功、游客 POST 创建/导入/其他写接口直接返回403；A07 已登录管理员创建→导入→实际来源命中，匿名/伪造 owner/跨源写拒绝；A08 所有17模块编译并校验真实二进制来源。Web 临时key真实调用交给用户，不替代构建真实模型门禁。

公共 HTTP 范围只含内置 CMRC；私人管理笔记本不自动发布。POST /api/demo/chat 接受非空≤1024字符 question，固定服务端知识库范围。自由问题不读写共享缓存，原精选题无临时key缓存语义保留。游客 GET /api/notebooks、内置笔记本 documents/suggestions、GET /api/demo/documents/{document_id} 分页原文、GET /api/auth/session、GET /api/llm/config 仅返回无凭据配置；私有管理入口需登录。默认 OpenRouter 凭据仅保存于服务端。公开原文接口固定 cmrc2018-demo source 前缀并复用 RagService 分页读取（offset>=0，每页最多20块），不能通过路径/参数访问私人范围。
