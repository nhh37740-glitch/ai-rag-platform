# 公开研发文档问答演示 HTTP 契约

本契约只约束 apps/agent-server 的 HTTP 适配，不修改已发布模块 facade。由独立容器设置 PUBLIC_DEMO=1 启用，私有工作区保持原行为。

## 范围与模式

- 只加载 data/kb/cmrc2018-demo 的内置公开资料，不读取用户笔记本或 agent-files；容器不挂载私有服务数据卷。
- 只注册五个只读 RAG 工具，不能创建文件、保存对话、上传或创建笔记本。
- DEMO_PROVIDER=mock：明确使用 MockProvider；DEMO_PROVIDER=deepseek：必须有服务器凭据，缺凭据拒绝启动，不能静默退回 Mock。凭据仅从服务器环境注入，不接受浏览器 API key。
- GET /api/demo 在原字段外增加 public_demo、read_only、provider、embedding；公开固定问题列表由现有 suggested_questions 提供。
- 公开进程的根页面返回独立演示页。静态资产、GET /api/demo、POST /api/demo/chat、GET /api/trace/{trace_id} 是唯一路由范围；其余 API 和非允许方法返回 403/405。私有模式下 POST /api/demo/chat 返回 404。

## POST /api/demo/chat

请求 JSON 只有 question 字段（非空字符串，必须与当前 suggested_questions 中的一项精确相等）。不允许额外字段，不接受 user_id/session_id/scope/key；限制请求正文大小（4 KiB），拒绝非 JSON、无效字段或非精选问题（422）。含 x-deepseek-api-key 或 Authorization 的请求拒绝（403）。服务端固定 knowledge_base_ids=[cmrc2018-demo]，使用新生成的请求/用户/会话 id，禁止复用私有记忆。

成功（200，Cache-Control: no-store）：

```json
{
  "answer": "本次模型输出",
  "trace_id": "生成的 trace id",
  "knowledge_base_ids": ["cmrc2018-demo"],
  "provider": "deepseek",
  "embedding": "hash",
  "read_only": true,
  "cache_hit": false
}
```

provider 只有 mock/deepseek；embedding 反映实际配置，不把 hash 命名为 BGE。仅真实输出/trace 可以展示，Mock 可原样返回检索工具 JSON。引用与检索结果取自实际 rag span，不能预填案例结果。

公开入口检查本次 trace 至少有一次成功 rag 检索并有内置范围的来源命中；否则返回 502，不把未检索答案列为成功。工具返回失败、无命中或模型异常如实错误；本契约不宣称自然语言引用已通过语义真实性验证。

真实模型调用限制：同一进程最多一项未命中缓存的请求在执行，忙时返回 429；执行总超时 90 秒返回 504。按固定 question 缓存成功答案与原 trace 最多 300 秒，命中时 cache_hit=true，前端明确标注为缓存结果；失败不缓存。最多缓存当前精选问题数，不能无限扩大。

## GET /api/trace/{trace_id}

保持原 SpanEvent 数组结构（trace_id/span/start_ns/end_ns/status/error/meta）；只允许读取该公开进程生成的 trace，未找到返回空数组。静态页将 agent/llm/tool/rag 的真实 span 显示为执行记录；rag 的 meta 中 query/knowledge_base_ids/hit_count/hits 为来源依据。

## 验收

Jenkins 在目标平台已编译模块的环境中验证：允许的固定问题→实际 trace；无检索成功结果拒绝；错误/超时/并发与缓存；禁止写 API、参数扩权与浏览器 key；不读取私人目录；正常私有模式已有功能仍通过。公开部署使用独立新数据卷；编译和模块原始契约门禁保留。
