# skill_runtime

Skills 注册、选择与惰性加载模块。

`SkillRegistry.load_dir()` 扫描 `skills/*/SKILL.md`，只读取 frontmatter 中的
`name` / `description` / `version` / `triggers` / `always` 元数据。
`SkillRegistry.render(ctx, query)` 再选择常驻技能或触发词匹配的技能，
通过 `SkillDef.load` 读取完整指令。

示例：

```python
from skill_runtime import SkillRegistry

registry = SkillRegistry()
registry.load_dir("skills")
instructions = registry.render(ctx, user_query)
```

`always: true` 用于每轮都必须可见的操作规则；`triggers` 用于按查询内容加载专项技能。
