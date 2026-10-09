# 管理员知识工作区 HTTP 契约

本契约只修改 apps 的 HTTP 权限和展示适配，保留笔记本、文档转换和检索的现有模块 facade。公开 PUBLIC_DEMO 容器和私人数据卷保持隔离。

## 权限边界

管理入口复用既有服务的管理员登录。反代必须验证该登录的有效性、管理员角色及指定拥有者，删除客户端传入的内部认证头，仅在认证通过后注入服务器间认证证明。后端再次验证证明及拥有者；证明只从服务器配置注入，不返回给浏览器。

内部头固定为 `X-Rag-Proxy-Token`（服务器证明）、`X-Rag-User-Id`（已验证拥有者标识）和 `X-Rag-Role: admin`。三个头各只能出现一次；后端精确比较拥有者和角色，以恒定时间比较证明。管理代理必须覆盖或移除所有同名客户端头。`Origin` 必须保留原浏览器值；禁止代理伪造同源 Origin。

`RAG_ADMIN_AUTH=proxy` 启用后端边界，必须同时配置至少 32 字节的 `RAG_ADMIN_PROXY_TOKEN`、精确的 `RAG_ADMIN_OWNER_ID` 和 HTTPS `RAG_ADMIN_ORIGIN`，缺少或无效配置拒绝启动。原回环开发工作区使用 `local` 模式；该模式不得通过公网反代开放。生产管理反代必须指向 proxy 模式实例。

除了 GET /api/demo（公开语料元信息兼容容器健康检查），私有页面、资产、OpenAPI、笔记本和文档清单、上传进度、模型设置、聊天、trace 及未知路由都必须认证；未认证或身份不匹配返回 403。不开放 WebSocket。所有管理响应包含 `Cache-Control: no-store`。

POST/PUT/PATCH/DELETE 等非安全方法及 GET /api/chat/stream 必须携带与配置精确一致的 Origin，并拒绝跨站 Sec-Fetch-Site。聊天上下文中的 user_id 由已认证拥有者决定，客户端不能冒用其他身份。GET SSE 可能调用写工具，不能按只读请求放行。

## 原业务接口

- POST /api/notebooks：原名称、说明字段创建笔记本；返回原 201 结构。
- POST /api/notebooks/{id}/files：原 multipart 上传、类型与大小限制以及 Markdown 转换/分块入库；返回原 201 结构。
- GET /api/uploads/{id}：仅同一拥有者可读取处理进度。
- GET /api/notebooks、文档清单、建议问题、POST /api/chat 和 trace：原接口，仅限管理身份。
- GET /api/admin/session：仅返回认证模式、拥有者标识和管理员权限，不返回任何模型或认证凭据。

## 验收

服务器 Docker/Jenkins 在实际编译产物环境检查：未登录、普通账号、冒用身份/内部头、错误证明、重复认证头、跨站写入和 SSE 均拒绝；认证后的指定管理员可创建并导入文档，重启后元数据及范围检索仍有效。公开 API 继续拒绝创建、上传和私有读取，公开容器不能读取私有目录。真实 HTTPS 浏览器验证登录、创建、导入及检索，缺少凭据时如实显示 Mock/hash。
