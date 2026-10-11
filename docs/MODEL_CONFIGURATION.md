# Provider、模型目录与管理员额度设计

任务：RAG-NOTEBOOK-20261011；日期：2026-10-11（北京时间）。状态：正式设计，provider/model 管理界面与重置接口待实现；现有服务只有环境配置、免费模型校验和全站每日20次。

## 表和边界

| 表 | 主要字段 | 作用 |
| --- | --- | --- |
| llm_providers | provider_id、name、adapter、base_url、secret_ref、enabled、updated_at | 服务商连接配置；adapter和域名白名单由服务器决定，secret_ref只引用服务器凭据，不保存key正文 |
| llm_models | provider_id、model_id、name、pricing、context_length、input_modalities、output_modalities、supported_parameters、available、last_seen_at、catalog_version | 模型目录缓存；(provider_id,model_id)联合主键；价格保存原始十进制字符串，免费资格由业务重新判定 |
| llm_settings | scope、provider_id、model_id、revision、updated_by、updated_at | 全站默认模型，外键引用模型；配置版本比较更新，避免两位管理员覆盖 |
| web_query_usage | scope、local_date、used、reset_generation、revision | 全站北京时间每日20次问答；事务预占，一次接受的问答计一次，Agent内部多轮模型调用不等于一次上游请求 |
| admin_audit | event_id、actor_user_id、action、before、after、reason、request_id、created_at | 配置变更和额度重置审计；不得记录密钥、请求正文、cookie或私人文档 |

公开入口与成员入口消费同一份全站配置、计数和审计数据库；私人笔记本数据库独立。不要把共享配置放进某个笔记本成员表。模型业务归 agent-facade，配置持久化归 data-facade/storage，管理员权限与额度规则归 auth-facade，agent-server只做HTTP装配。Notebook manager不能管理全站模型或额度。

## 免费目录同步

服务启动时向固定官方 GET https://openrouter.ai/api/v1/models 查询模型目录；服务器提供凭据，客户端不可指定查询地址。使用有界超时和响应大小限制，完整解析成功后事务更新目录版本；并发进程通过刷新租约避免重复同步。目录是缓存，不以启动成功为实时可用保证。

后续请求发现目录超过1小时则触发一次刷新，管理员可手动刷新。失败保留上次完整缓存及错误时间；超过24小时的具体模型禁止作为新选择/新请求，默认 openrouter/free 仍可用。成功的完整目录中消失的模型标记 unavailable，不删除历史配置与审计。刷新不自动覆盖管理员选定模型。

可选择的具体模型必须同时满足：模型ID为 :free 变体、prompt/completion及所有返回的货币价格均可解析为有限且精确的0、支持文本输入输出及tools、仍在当前目录中。缺失必要字段、负价格或NaN均拒绝。不要只按名称含free判断，也不要把超低价格当免费。openrouter/free是官方免费路由，作为固定默认与免费回退项；禁止回退到auto或付费型号，禁止付费插件。服务器在每次请求开始重新校验选定配置，完整问答固定同一配置快照。

参考：[模型目录API](https://openrouter.ai/docs/api/api-reference/models/list-all-models-and-their-properties)返回价格、上下文和能力；[免费路由](https://openrouter.ai/docs/guides/routing/routers/free-router)按请求能力筛选免费模型并随机选择，供应可变化。上述刷新周期、24小时有效期和缓存策略是本项目设计，并非OpenRouter的官方保证。

## 管理员Web能力

全局管理员可查看provider状态/密钥是否配置、启停已支持provider、选定免费默认模型、查看缓存时间并刷新模型目录。Web只引用已有凭据，不能回显或导出key；新增未知adapter、任意base_url或启用付费模型不属于当前范围。所有变更验证可信管理员身份、同源请求、严格字段和配置版本，并写审计。

管理员可重置“今天全站已用次数”，原因必填，操作后恢复20次可用额度；保留重置前计数和当日累计消耗，不能清除审计。采用计数修改和审计同一事务，重置与并发预占不能丢失。此操作是原定全站每天20次的管理员例外，反复重置可以使当日累计超过20；界面应明确显示累计和重置次数。普通成员、笔记本manager和游客均无此权限。

重置只修改本地RAG问答额度，不能重置OpenRouter账号/API key的请求或信用额度。仍需处理上游429和Retry-After；[官方限额](https://openrouter.ai/docs/api_reference/limits)说明额度由上游执行，一次RAG问答可能包含多轮工具调用并消耗多次上游请求。

## 拟定API和验收

GET /api/admin/llm/providers；GET /api/admin/llm/models；POST /api/admin/llm/models/refresh；PATCH /api/admin/llm/settings（provider_id/model_id/expected_revision）；POST /api/admin/quota/reset（reason/expected_revision）；GET /api/admin/audit。现有GET /api/llm/config仅返回当前公开配置和额度摘要，不返回凭据或管理员审计。

实现前将签名加入specifications；验收覆盖免费价格与能力判定、收费型号拒绝、刷新失败/空目录/失效模型、并发刷新与配置修改、跨入口即时生效、普通用户越权与CSRF拒绝、额度重置并发和审计原子性、重启持久化、密钥不泄漏。完成状态另写验证记录，设计不代表已上线。
