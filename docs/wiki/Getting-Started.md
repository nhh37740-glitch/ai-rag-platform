# 快速使用

## 用户可以做什么

- 注册/登录账号，创建笔记本、上传文档并针对选定笔记本问答。
- 笔记本所有者可邀请成员，共享角色只有 `editor` 和 `viewer`。
- 查看带来源的回答；普通用户会话可保存，游客问答不保存历史。
- 管理员管理账号与 Provider/Model 配置。模型 API Key 只在服务器环境中保存，不向浏览器返回。

## 设计限制

- 账户、笔记本、成员、文档、会话和 Agent 配置存储在**同一个 SQLite 文件的六张业务表**。
- 管理员、游客、注册用户共用每日 100 次问答额度。
- 登录令牌位于进程内存，服务重启后需要重新登录。
- GitHub 代码功能与服务器当前部署状态可能不同，线上能力要以实际发布日志和验证为准。

详细规则以 [README](https://github.com/nhh37740-glitch/ai-rag-platform/blob/master/README.md) 与 [PLAN](https://github.com/nhh37740-glitch/ai-rag-platform/blob/master/docs/PLAN.md) 为准。
