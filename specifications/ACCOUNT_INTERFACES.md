# 本地账号、笔记本与单库接口

本文件规范见 `DOMAIN_INTERFACES.md` 的“0.3.0 用户授权重构的生效接口”。运行时只有 `RAGnotebook` 一个 HTTP 进程；auth-facade、data-facade、rag-facade、agent-facade 在同一进程内通过公开接口调用。旧 Media 会话代理与旧 ACL 不导入新库。
