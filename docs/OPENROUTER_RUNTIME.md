# RAG OpenRouter 默认配置与发布交接

日期：2026-10-10（北京时间）。用户授权默认使用其 OpenRouter 凭据、仅免费模型、全站每天共20次 Web 问答。此文件不含凭据。用户已授权提交、推送、通知构建发布维护并通过 Jenkins 上线；实际发布阶段以 Jenkins 和线上证据为准。

## 模块与配置

- `apps/agent-server/model_config.py` 解析服务端配置；现有 AgentService/make_provider 与 llm-gateway 复用 OpenAI 兼容调用，不新增网络服务。
- `LLM_PROVIDER=openrouter`，`OPENROUTER_MODEL=openrouter/free`，`OPENROUTER_API_KEY` 由服务端注入。仅允许免费路由或合法 `:free` 模型，不能指定付费模型、auto、额外后缀或付费回退。API 地址固定 `https://openrouter.ai/api/v1`。免费路由根据请求所需工具能力选择免费模型，依据：[OpenRouter 官方文档](https://openrouter.ai/docs/guides/routing/routers/free-router)。
- 本机专用 `.env.openrouter` 已写入用户提供的凭据，受 `.gitignore` 和 `.dockerignore` 排除。应用默认读取此文件；可用 `RAG_LLM_ENV_FILE` 指定运行配置路径。已有环境变量优先；测试设置此变量为空，禁止读本机凭据。
- 显式 `LLM_PROVIDER=mock` 不使用真实密钥；`LLM_PROVIDER=deepseek` 保留旧配置兼容。响应和 repr 不输出密钥，默认模型异常在记录 trace 前替换为固定错误。

## 日额度

`auth-facade@0.2.0/DailyQueryQuota` 实施业务规则；通过共享 StateStorePort 注入 `storage@0.3.0` 的原子计数，不 import 数据业务模块。SQLite BEGIN IMMEDIATE 保证多个连接同时占用时不超过20；全站固定服务端身份，不按浏览器传入 user/session/IP 分账。北京时间零点切换日期，重启、临时 key 和改变会话都不能增加额度。

POST /api/demo/chat、POST /api/chat、GET /api/chat/stream 共用额度。合法且未命中缓存的模型问答开始前占用一次；执行失败或超时不退还，非法输入、忙时拒绝及成功缓存命中不消耗。第21次返回429及 Retry-After；配置/结果响应只返回额度摘要。一个问答可能多次调用模型，OpenRouter 自身的上游请求限制另行生效，不能把20次问答等同20次模型 HTTP 请求。

持久目录默认 STATE_DIR/web-quota。公开与私人容器、多实例合并计数时，设置相同 `WEB_QUOTA_STATE_DIR` 并挂载同一独立可写卷；此卷只保存日计数，不共享私人知识或对话。使用不同目录会形成独立预算，生产发布不得用此方式扩大全站额度。

## 构建发布职责需要处理的资源

代码和 Windows 产物由项目维护准备；以下现有发布文件仍只支持 Mock/DeepSeek，需要构建发布职责适配后发布：

1. Jenkinsfile 的 PublicDemoProvider 选项及说明加入 openrouter；运行凭据由独立受控环境文件注入，不混用构建 DeepSeek 验收凭据。
2. scripts/deploy_public_demo.sh 的模式分支、候选启动和回滚元数据接受 openrouter，不覆盖凭据文件。
3. scripts/smoke_public_demo.py 接受 openrouter，检查免费模型和20次额度元数据；smoke 会占用问答额度，应计入发布当天预算。
4. compose.public-demo.yaml 和私人工作区运行配置选择 OpenRouter 凭据文件，并为两者配置同一独立额度卷；更新现有默认 Mock 标签/说明。凭据文件权限限制为部署账号可读，不进入镜像/ZIP/Git/聊天或构建日志。
5. Jenkins/Linux 构建全部 `.so` 并通过候选验收后再切换正式服务；记录部署版本、入口、额度及回滚证据。

项目维护将提交并推送已验收实现，按用户授权交接构建发布维护。上述发布资源由发布职责适配；生产入口需在 Jenkins 发布后验证。

## 本机验收证据

应用候选版本0.6.0；源码 leaf 90项、facade 39项通过；Windows Python3.11 二进制 leaf 90项、facade 39项通过；严格接口12项及151子项通过。HTTP 全量回归中34项通过，剩余公开回归在更新默认错误清理包装的旧断言后，所属4项公开组复验全部通过；全部35项应用用例已覆盖。新增HTTP用例验证20次成功、第21次429、重启不重置、SSE及临时key不能绕过。

实际 OpenRouter 凭据校验200；一次免费 API 调用200，路由至 nvidia/nemotron-3-super-120b-a12b:free，响应报告 cost=0。另在隔离临时状态中通过默认 OpenRouter 配置执行“什么是静电感应”真实 RAG 问答，HTTP200、非空答案、2次成功知识检索span，测试额度从20降至19，不改动生产计数。

JavaScript 语法检查、模块依赖方向检查、Git diff 空白检查通过。源码、接口文档、网页未发现 OpenRouter 密钥正文；专用配置被Git忽略。ZIP 构建仅选择运行目录与注册模块产物，不收集根目录 `.env.openrouter`。这些证据只证明本机构建与验收，不证明线上版本已切换。
