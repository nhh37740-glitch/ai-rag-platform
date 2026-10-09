# 0.2.1
- 共享接口包迁移为 core_specifications；重新构建二进制并保持本模块接口行为。

# Changelog

## 0.2.0 - 2026-09-11

- 新增 `SkillRegistry.render(ctx, query)`，渲染选中技能的完整 `SKILL.md` 指令。
- 新增 `always` 常驻技能和 `triggers` 查询触发元数据。
- 保留 `list` / `load` 行为及 `SkillDef.load` 惰性加载兼容性。
