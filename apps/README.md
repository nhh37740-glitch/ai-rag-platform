# apps — 集成应用层

本目录是唯一的业务集成入口，只消费 `artifacts/` 中的二进制模块和
`specifications/` 中的共享接口，不直接导入 `modules-src/`。

| 目录 | 职责 | 入口 |
|---|---|---|
| `ragnotebook/` | RAGnotebook HTTP API、鉴权中间件、上传与静态资源 | `ragnotebook/server.py` |
| `web/` | 只调用 RAGnotebook HTTP API 的浏览器页面 | `web/index.html` |

## 边界

- `ragnotebook` 只可导入四个业务 facade（`auth_facade`、`data_facade`、`rag_facade`、
  `agent_facade`）和共享公共接口；不得导入一级模块、SQLite 或向量实现。
- `runtime_boundary.py` 在导入业务模块前读取 `registry.json`，只允许从 `artifacts/`
  加载 `.pyd/.so`；任何模块从 `modules-src/` 或 `.py` 加载都会导致启动失败。
- 网页只调用 API，不内嵌业务规则；模型密钥只从服务器环境读取。
- 应用测试在隔离的临时 `STATE_DIR` 中运行，不读取本机私有凭据。
