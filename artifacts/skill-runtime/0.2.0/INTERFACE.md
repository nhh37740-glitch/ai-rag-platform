# INTERFACE

- `SkillRegistry.load_dir(path) -> None`：扫描 `skills/*/SKILL.md`，读取 `name` / `description` / `version` / `triggers` / `always` 元数据。
- `SkillRegistry.list(ctx) -> list[SkillDef]`：列出已注册技能，保留惰性 `load` 回调。
- `SkillRegistry.load(ctx, name) -> SkillDef`：按名称取得技能定义，未找到时抛出 `KeyError`。
- `SkillRegistry.render(ctx, query) -> str`：选择 `always: true` 或命中 `triggers` 的技能，调用 `SkillDef.load` 惰性读取并合并完整 `SKILL.md` 指令。

`triggers` 支持列表或行内写法：

```yaml
always: false
triggers:
  - 知识库
  - RAG
```
