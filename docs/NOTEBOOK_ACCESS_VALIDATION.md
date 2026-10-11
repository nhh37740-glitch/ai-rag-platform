# RAG业务模块验收与发布交接

任务：RAG-NOTEBOOK-20261011；日期：2026-10-11（北京时间）。本文件只记录完成阶段，正式设计为[NOTEBOOK_PERMISSIONS.md](NOTEBOOK_PERMISSIONS.md)、[MODEL_CONFIGURATION.md](MODEL_CONFIGURATION.md)，业务归属索引为[BUSINESS_CHANGE_MAP.md](BUSINESS_CHANGE_MAP.md)，接口以specifications为准。

## 已修改与模块归属

| 业务模块 | 本次结果 | 支撑服务/接口 |
| --- | --- | --- |
| auth-facade 0.4.0 | 可信普通用户登记；笔记本角色与权限；多连接事务版本冲突后重新授权；归档目录无读取/问答权限 | auth-runtime 0.4.0证明；NotebookStorePort；members API与Web成员管理 |
| data-facade 0.2.0 | 笔记本目录创建/查询/迁移/改名/软归档恢复；目录表为事实来源，旧文件资产保留 | storage 0.4.0 NotebookStore与7张关系表；notebooks API与Web目录操作 |
| agent-facade 0.3.0 | 默认简体中文与只读工具授权；既有模型环境选择与免费校验提取为业务接口resolve_model_config | agent-runtime 0.5.0每轮语言/工具约束；ModelConfiguration共享类型；chat/SSE及model_config兼容适配 |
| rag-facade 0.1.0 | 接口保持，回归验证当前授权笔记本检索/引用，拒绝工具伪造扩大范围 | rag-tools/rag-core与检索trace |

集成版本agent-server 0.8.0、core_specifications 0.6.0、规范集合1.0.0。HTTP装配、真实Media会话登录、角色展示、历史/trace/上传进度隔离和同源校验保留。本次不创建Media账号，不修改共用Nginx/Jenkinsfile/部署脚本。

初稿e7dc650中的JSON ACL已被本次关系表实现替代；角色、权限、成员和目录不再用整个JSON字典保存。旧JSON ACL只作为启动迁移输入，标记成功后不再重复导入。旧目录中的文档manifest仍存文件，笔记本名称/说明/归档/所有者以数据库为准。

Provider/model表、动态刷新目录、管理员Web配置和本地额度重置已写正式设计，尚未实现；不得作为本次发布成果。现有全站共享默认OpenRouter免费模型与每日20次政策保持，MODEL_CONFIGURATION记录重置属于管理员例外以及上游额度无法被本地重置。

## 本机已验证与已构建

Windows Python3.11.15，hash embedding；18个注册模块严格从.pyd加载，4项关系表/配置业务版本制品已重建。

| 验收 | 结果 |
| --- | --- |
| 基础模块源码 / 二进制 | 96 / 96项通过，各25子项 |
| 业务模块源码 / 二进制 | 48 / 48项通过，各68子项 |
| 严格接口规范与打包契约 | 12项、153子项通过 |
| HTTP全量应用 | 38项、5子项通过；一个既有pytest anyio重写提示，无失败 |
| 业务域装配与检索回归 | 12项、11子项通过 |
| 运行边界、模块依赖、JS语法、diff | 通过；18个已发布扩展，COMPILED_AGENT_OK |

数据库验收覆盖外键/唯一约束、未知用户/角色写入回滚、两个连接旧版本拒绝、四个授权实例并发40成员无丢失、manager并发被撤权后重新授权拒绝、数据重启持久化、角色种子不覆盖、归档保留成员。完整服务启动迁移保留原Markdown与索引，重新启动不恢复已撤成员且不覆盖数据库改名。

HTTP覆盖viewer拒绝导入/成员管理/改名、editor导入、manager只管理授权笔记本且不能归档、全局管理员归档/恢复、公开内置资料只读、未知用户先登录登记、伪造身份/角色及body.user_id无效、严格请求字段、CSRF拒绝、跨笔记本问答/SSE拒绝、私人trace/进度仅操作本人或管理员可读且撤权后拒绝、模型伪造写工具拒绝、用户与笔记本范围隔离历史。

此前同任务真实默认模型验收：仅发送仓库公开CC BY-SA CMRC2018样本，独立临时额度与数据，HTTP200、openrouter/free、152中文字符/19拉丁字母、2次实际RAG检索span，trace_id=06c7883a5adb4f5097ab406dc8e92aea。生产额度消耗0。一次结果不能保证每个模型都遵循语言约束；本轮提取模型环境配置保持原选择行为。

## 发布交接和线上验收要求

用户已授权提交/推送GitHub、Jenkins构建发布及通知相关职责聊天。交构建发布维护执行：Linux编译18模块、严格/行为/HTTP测试、公开/成员/登录服务版本部署，沿用服务器凭据及共享全站额度卷。新notebook.sqlite属于私人状态卷；启动迁移前备份私人目录、state.sqlite和卷快照，回滚需同时恢复发布前数据副本，避免旧版本忽略新表授权而误报。

Nginx现有配置动态转发/verify给出的X-Rag-User-Id/X-Rag-Role；需核对线上生效配置，无须预先修改。若需要网关变更交平台运维。候选用合成用户/资料测试完整成员矩阵和迁移；真实Media账号验收仍用已有授权owner，不将注入身份测试说成真实账号登录。

线上至少核验：真实公开中文问答、实际检索、owner登录/退出、匿名私人拒绝、免费型号/共享每日20次、旧笔记本数量/名称/文档保留、真实部署提交与三服务版本。普通成员HTTPS真实登录需已有已授权测试账号，缺少时如实记录此项未验收。

当前状态：已修改、已验证、Windows制品已构建；本次版本未部署、未线上验收。待回填本次提交/PR/Jenkins/实际部署证据。
