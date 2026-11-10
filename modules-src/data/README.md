# data — 数据与持久化业务域

负责唯一 SQLite 数据库、向量/记忆存储和会话数据。读者入口是
`data-facade/INTERFACE.md`；集成侧只通过 `DataService` 调用本域。

| 模块 | 职责 |
|---|---|
| `data-facade` | 本域唯一公开门面：六张关系表、向量与记忆端口 |
| `storage` | SQLite 关系存储、向量持久化与原子计数 |
| `memory` | 会话记忆与历史快照 |

允许依赖：本域模块、`core_specifications`、`platform/observability`。
禁止创建第二个数据库文件、额外业务表或自动迁移；确需改表先更新冻结方案。
