# Contract Layer（接口规范层）

本目录是整个系统的**唯一共享"源码"**：只定义接口与数据结构，无任何实现。所有模块 subagent 与集成侧都以此为准。

- `core_specifications/`：`RequestContext`、`ChatMessage`、`ToolDef`、`ToolCall`、`RetrievalResult`、`MemoryEntry`、`SkillDef`、`SpanEvent` 等共享类型（纯 Python，无外部依赖）。
- `INTERFACES.md`：每个模块的公开接口（函数/签名/职责），即各 subagent 的任务书。
- `API_SCHEMA.json`：接口的机器可读形式（模块 → facade → 方法 → 参数/返回类型），供结算/校验/生成任务书使用；是 `INTERFACES.md` 的结构化镜像。
- `test_specification.py`：接口规范闸门，从 `registry.json` 指定的 `artifacts/` 加载目标平台扩展，对照 `API_SCHEMA.json` 校验公开参数名与返回类型，并回放包内接口规范测试。
- `WEB_DEMO.md`、`WEB_DEMO_SCHEMA.json`：独立公开演示的 HTTP 接口规范，限定固定问题、只读 CMRC 范围和实际检索 trace；不改变业务模块门面。
- 任何模块实现不得修改本目录；接口变化必须先改这里，再同步 `docs/PLAN.md`。

## 这个目录告诉你什么

- **你怎么被调用**：`RequestContext` 永远是第一个入参（命名 `ctx`），`specification_version` 全局唯一；改任何公共签名要先改这里。
- **你暴露什么**：`API_SCHEMA.json` 的 `modules.<id>.facade` 给出每个模块的公开符号、参数与返回类型；当前 Linux Jenkins 构建用 Cython 生成 `.so`，Windows 目标生成 `.pyd`。独立 Windows worker 的 Nuitka 交付仅在相应流程中使用。
- **你如何交付**：见 `INTERFACES.md` 的「模块生命周期」——在根仓库 `modules-src/<module>` 中维护独立 Python 包、接口规范与测试，由根仓库流水线编译、校验并将版本化产物写入 `artifacts/<module>/<version>/` 与 `registry.json`。
- **你不得做什么**：集成侧只 import 编译后的二进制；不得在 `apps/` 或 `artifacts/` 里放实现源码；不得引入接口规范约束之外的第三方库。
