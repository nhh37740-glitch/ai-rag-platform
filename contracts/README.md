# Contract Layer（契约层）

本目录是整个系统的**唯一共享"源码"**：只定义接口与数据结构，无任何实现。所有模块 subagent 与集成侧都以此为准。

- `core_contracts/`：`RequestContext`、`ChatMessage`、`ToolDef`、`ToolCall`、`RetrievalResult`、`MemoryEntry`、`SkillDef`、`SpanEvent` 等共享类型（纯 Python，无外部依赖）。
- `INTERFACES.md`：每个模块的公开接口（函数/签名/职责），即各 subagent 的任务书。
- `API_SCHEMA.json`：接口的机器可读形式（模块 → facade → 方法 → 参数/返回类型），供结算/校验/生成任务书使用；是 `INTERFACES.md` 的结构化镜像。
- `test_contract.py`：契约闸门，集成侧对每个已发布二进制校验 facade 符号与入参、并重跑各模块自带契约测试、核对 `artifacts/` 与 `registry.json` 一致性。
- 任何模块实现不得修改本目录；接口变化必须先改这里，再同步 `docs/PLAN.md`。

## 这个目录告诉你什么

- **你怎么被调用**：`RequestContext` 永远是第一个入参（命名 `ctx`），`contract_version` 全局唯一；改任何公共签名要先改这里。
- **你暴露什么**：`API_SCHEMA.json` 的 `modules.<id>.facade` 给出每个模块的公开符号与重载；`delivery` 字段说明该模块是 `mypyc`/`Cython` 的 `.pyd`，还是 `Nuitka` 的 `.exe`。
- **你如何交付**：见 `INTERFACES.md` 的「模块生命周期」——在 `modules-src/<module>` 独立仓库内开发、测试、编译、算 checksum，发布到 `artifacts/<module>/<version>/` 并登记 `registry.json`。
- **你不得做什么**：集成侧只 import 编译后的二进制；不得在 `apps/` 或 `artifacts/` 里放实现源码；不得引入契约约束之外的第三方库。
