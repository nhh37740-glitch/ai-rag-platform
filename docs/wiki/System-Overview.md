# 系统架构

```text
浏览器 → RAGnotebook 唯一 HTTP API
                ├─ auth-facade  账号与权限
                ├─ data-facade  唯一数据库入口
                ├─ rag-facade   导入与检索
                └─ agent-facade 问答与模型管理
                        ↓
                 公开接口与底层能力模块
```

- **模块边界**：应用 HTTP 路由不直接导入一级模块、SQLite 或具体向量实现。
- **接口先行**：`specifications/` 约定公共接口和依赖关系。
- **源码隔离**：`modules-src/` 只用于开发和编译；运行应用从 `artifacts/` 加载已登记的二进制扩展。
- **单库**：统一 SQLite 六张表，不随意新增第二套数据库或迁移逻辑。

文档不宣称 pgvector、FAISS 等候选能力已实现。以 [实施计划](https://github.com/nhh37740-glitch/ai-rag-platform/blob/master/docs/PLAN.md) 与 [API Schema](https://github.com/nhh37740-glitch/ai-rag-platform/blob/master/specifications/API_SCHEMA.json) 为准。
