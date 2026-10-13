# RAGnotebook

RAGnotebook 是一个面向浏览器的文档问答应用，支持账号注册与登录、笔记本创建和共享、文档上传、带来源问答、会话历史，以及管理员账号和模型管理。

浏览器只访问 `RAGnotebook` HTTP API。后端运行在一个进程中，内部由 `auth-facade`、`data-facade`、`rag-facade`、`agent-facade` 四个业务模块处理请求。HTTP 路由不直接访问数据库、向量库或其他一级能力模块。

## 数据与账号

全部关系数据和文档向量共用一个 SQLite 文件，固定六张表：`users`、`notebooks`、`notebook_members`、`documents`、`conversations`、`agent_data`。首次启动创建结构；已有数据库结构不符时启动失败，不执行迁移。旧账号和笔记本不导入。

首次启动通过服务器环境配置管理员账号，并创建固定游客账号。普通用户可自行注册。笔记本所有者由 `notebooks.owner_user_id` 表示；成员角色只有 `editor`、`viewer`。项目管理员身份与笔记本所有权相互独立。游客可作为 `viewer` 被共享，游客问答不保存历史。所有身份共用每天 100 次问答额度。

登录令牌只保存在后端进程内存。服务器重启后需要重新登录；每个请求都会检查账号是否有效。模型密钥只从服务器环境读取，模型选择保存在 `agent_data`，API 不返回密钥。

## 目录

- `apps/ragnotebook/`：RAGnotebook HTTP API 与网页资源。
- `apps/web/`：只调用 RAGnotebook API 的浏览器页面。
- `modules-src/*-facade/`：四个业务模块的公开接口。
- `modules-src/` 其他目录：解析、检索、存储等能力模块。
- `specifications/`：共享类型与模块接口规范。
- `scripts/`：依赖边界检查、测试、编译和发布制品脚本。

## 源码测试

```sh
python scripts/check_module_dependencies.py
python scripts/run_tests.py --mode source --group leaf
python scripts/run_tests.py --mode source --group facade
python scripts/run_tests.py --mode source --group scripts
```

Docker/Jenkins 构建还会编译 Cython 扩展、验证二进制加载边界并运行应用集成测试。生产构建与部署状态以构建发布记录为准。

## 部署

服务器首次启动需私有的 `/home/ubuntu/.config/ai-rag/bootstrap-admin.env`，包含 `RAG_BOOTSTRAP_ADMIN_USERNAME` 和 `RAG_BOOTSTRAP_ADMIN_PASSWORD`，权限为 0600；Compose 和候选容器均显式加载它。凭据不提交到 Git。新版本使用新的命名数据卷保存六表数据库，旧卷保留供回滚。游客直接使用同一 RAGnotebook 服务和统一问答 API。旧的独立公开演示与双服务管理员发布入口不再由 Jenkins 发布。
