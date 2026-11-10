# platform — 跨域公共运行时

存放所有业务域都可使用的公共设施。读者入口是 `observability/INTERFACE.md`。

| 模块 | 职责 |
|---|---|
| `observability` | 结构化日志、span 耗时与 trace 查询 |

允许依赖：`core_specifications` 与标准库。本域不得依赖任何业务域。
