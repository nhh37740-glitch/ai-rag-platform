# Web 页面

静态 HTML/CSS/JavaScript，不编译为 Python 模块。仅调用后端 API。由 agent-server 托管，随运行镜像和 ZIP 发布。

公开页 `public_demo.html` 从 `api/auth/session` 显示服务端身份，读取公开笔记本与
CMRC 文档列表；支持最多 1024 字的自由问题和精选问题。原文通过
`api/demo/documents/{document_id}?offset=...` 分页查看，每页最多 20 块。
页面不提供游客创建或导入入口，管理员登录链接为 `admin/login/`。

管理员工作区 `index.html` 读取同一身份接口，只有服务端返回的管理员及对应
permissions 才启用创建、导入与私人笔记。API 使用相对地址，兼容本机根路径和
`/projects/apps/rag/admin/` 代理前缀。身份确认前禁用写操作，401/403 后禁用权限。
登录页保持现有代理认证协议。

临时 DeepSeek key 仅保留在页面内存，在 HTTPS 或本机安全页面输入；仅进入问答
POST 请求头，刷新、离开页面或退出登录清除，不写 URL、聊天内容或浏览器存储。
