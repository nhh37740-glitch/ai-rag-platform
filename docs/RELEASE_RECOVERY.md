# 数据迁移发布与失败恢复

任务：RAG-NOTEBOOK-20261011；日期：2026-10-11（北京时间）。笔记本规则见 [NOTEBOOK_PERMISSIONS.md](NOTEBOOK_PERMISSIONS.md)，本文只维护发布恢复。

Jenkins 完成源码、Linux二进制、接口、HTTP与真实模型门禁并归档后，针对选中的私人／公开／管理员服务执行 `sudo python3 scripts/release_state.py backup --build "$BUILD_NUMBER" --targets ...`，再运行原有候选及 Compose 发布步骤。快照目录为 `/home/ubuntu/backups/ai-rag/build-<号>`，权限0700，禁止覆盖已有快照。

备份包含所选服务实际状态、用户笔记本、Agent文件卷以及旧镜像ID和运行配置文件路径，不包含密钥文件正文。停止所选容器后再快照，使SQLite数据库、WAL和文档目录处于一致的停止状态。快照至所选服务重新启动期间存在发布停机窗口；未选中的服务不停止。快照拒绝符号链接、硬链接、设备与越界路径，失败会重新启动原容器。

Jenkins失败／中止时调用同脚本 `restore`：先验证全部归档SHA256与路径，再停服务，恢复原数据和旧镜像、沿用原配置路径并等待健康。没有完整manifest时不恢复，已经完成恢复的快照不重复应用。旧镜像另保留 `state-rollback-build-<号>` 标签。

共享 `ai-rag-web-quota` 和模型缓存卷不在备份／恢复范围。回滚不撤销已消耗的问答次数，不创建或重设身份账号，不更改共用Nginx。快照保留在服务器私有目录，报告只记录位置和校验值，不收集私人文档正文。生产恢复应始终同时恢复数据和镜像，不能只将旧镜像指向已经迁移的数据。

服务器Python3.14的默认tar数据过滤器会移除UID/GID，单传numeric_owner不足以保留属主。脚本先验证全部归档和规范路径，仅允许普通文件/目录，再显式保留受验证成员的数字属主和原权限；实际Docker恢复须验证UID10001仍能读取SQLite并通过健康检查。
