# INTERFACE

- `SkillRegistry.load_dir(path)`：扫描 `skills/*/SKILL.md`。
- `SkillRegistry.list(ctx) -> list[SkillDef]` / `load(ctx, name) -> SkillDef`（惰性展开）。
