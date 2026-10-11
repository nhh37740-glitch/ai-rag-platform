# RAG业务模块变更归属

任务：RAG-NOTEBOOK-20261011；日期：2026-10-11（北京时间）。正式索引；验收与发布状态见NOTEBOOK_ACCESS_VALIDATION.md。

| 用户能力 | 唯一业务归属 | 服务/接口实现位置 | 正式依据与状态 |
| --- | --- | --- | --- |
| 身份认证、普通登录用户、全局管理员证明 | auth-facade | AuthService → auth-runtime；admin_login可信会话；/api/auth/session | AUTH_INTERFACES；已实现待本轮回归 |
| 笔记本viewer/editor/manager权限、成员管理、即时撤权 | auth-facade | NotebookStorePort；storage成员/角色/权限表；members API与Web成员界面 | NOTEBOOK_PERMISSIONS；关系表实现中 |
| 笔记本目录、创建、改名、软归档/恢复、旧目录迁移 | data-facade | DataService目录方法 → storage NotebookStore；notebooks API及Web | NOTEBOOK_PERMISSIONS；关系表实现中 |
| 全站每日20次规则 | auth-facade | DailyQueryQuota → StateStorePort；共享持久数据库；公开与成员入口同一计数 | OPENROUTER_RUNTIME；既有能力保持 |
| 中文回答与只读工具执行、按笔记本隔离历史 | agent-facade | AgentService → agent-runtime语言和工具约束；chat/SSE适配 | DOMAIN_INTERFACES；已实现待回归 |
| 当前授权笔记本内检索、引用和检索trace | rag-facade | RagService → rag-tools/rag-core；应用传已授权范围 | DOMAIN_INTERFACES；保持既有接口，回归越权 |
| 模型环境配置、免费资格；计划provider/model目录管理 | agent-facade | resolve_model_config已提取既有策略；计划ModelCatalog业务接口与data-facade/storage表持久化；管理员HTTP/Web装配 | MODEL_CONFIGURATION；环境配置已归业务，目录/Web管理设计待实现 |
| 管理员重置全站本地日额度与权限 | auth-facade | 计划额度重置业务接口；data-facade/storage计数与审计事务；管理员HTTP/Web | MODEL_CONFIGURATION；设计已写，待实现 |

每项验收、CHANGELOG和发布交接以业务模块为单位，再列支撑服务/接口。agent-server拥有HTTP身份上下文、请求校验、生命周期装配及响应转换，不拥有角色判定、语言策略或模型选择策略。apps/web按服务返回的权限显示操作，不能授予权限。storage不校验HTTP管理员；auth-runtime只验证证明，不依赖Agent/RAG/Data业务。模块归属不等于必须独立部署一个容器。
