from __future__ import annotations

import os
import re
from typing import Callable, Dict

from core_specifications import RequestContext, SkillDef

__version__ = "0.2.1"


class SkillRegistry:
    """扫描 skills/<name>/SKILL.md，命中后惰性加载指令。"""

    def __init__(self) -> None:
        self._skills: Dict[str, SkillDef] = {}
        self._metadata: Dict[str, dict[str, object]] = {}
        self._root: str | None = None

    def load_dir(self, path: str) -> None:
        self._root = path
        if not os.path.isdir(path):
            return
        for entry in os.listdir(path):
            d = os.path.join(path, entry)
            md = os.path.join(d, "SKILL.md")
            if os.path.isdir(d) and os.path.isfile(md):
                name, desc, ver, triggers, always = self._parse_manifest(md)
                if not name:
                    name = entry
                self._skills[name] = SkillDef(name, desc or entry, ver or "0.1.0", self._loader(md))
                self._metadata[name] = {"triggers": triggers, "always": always}

    @staticmethod
    def _loader(md: str) -> Callable[[], str]:
        def _load() -> str:
            with open(md, encoding="utf-8") as f:
                return f.read()

        return _load

    def list(self, ctx: RequestContext | None = None) -> list[SkillDef]:
        return list(self._skills.values())

    def load(self, ctx: RequestContext, name: str) -> SkillDef:
        if name not in self._skills:
            raise KeyError(name)
        return self._skills[name]

    @staticmethod
    def _parse_manifest(
        md: str,
    ) -> tuple[str | None, str | None, str | None, list[str], bool]:
        frontmatter_lines: list[str] = []
        with open(md, encoding="utf-8") as f:
            if f.readline().lstrip("\ufeff").strip() == "---":
                for line in f:
                    if line.strip() == "---":
                        break
                    frontmatter_lines.append(line)

        # SKILL.md only needs a deliberately small YAML-compatible subset.  Keeping
        # the parser here avoids adding a runtime dependency solely for metadata,
        # and stops before the instruction body so full content remains lazy.
        frontmatter = "".join(frontmatter_lines)

        def scalar(key: str) -> str | None:
            item = re.search(rf"(?m)^{re.escape(key)}:[ \t]*([^\r\n]*)$", frontmatter)
            if not item:
                return None
            value = item.group(1).strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1].strip()
            return value or None

        trigger_values: list[str] = []
        inline = scalar("triggers")
        if inline:
            if inline.startswith("[") and inline.endswith("]"):
                inline = inline[1:-1]
            trigger_values.extend(part.strip().strip("\"'") for part in inline.split(","))

        block = re.search(
            r"(?ms)^triggers:[ \t]*\r?\n((?:^[ \t]+-[ \t]*[^\r\n]+\r?\n?)*)",
            frontmatter,
        )
        if block:
            trigger_values.extend(
                item.strip().strip("\"'")
                for item in re.findall(r"(?m)^[ \t]+-\s*([^\r\n]+)$", block.group(1))
            )

        triggers = list(dict.fromkeys(value for value in trigger_values if value))
        always = (scalar("always") or "").casefold() in {"true", "yes", "1", "on"}
        return scalar("name"), scalar("description"), scalar("version"), triggers, always

    def render(self, ctx: RequestContext, query: str) -> str:
        """Render complete instructions for skills selected by metadata.

        An ``always`` skill is present on every turn.  Other skills are selected
        when one of their explicit trigger phrases occurs in the query.  Skills
        without trigger metadata retain a conservative name/description match.
        The loader is invoked only for selected skills, preserving lazy loading.
        """

        normalized_query = query.casefold()
        rendered: list[str] = []
        for skill in self._skills.values():
            metadata = self._metadata.get(skill.name, {})
            triggers = [str(value) for value in metadata.get("triggers", [])]
            selected = bool(metadata.get("always")) or any(
                trigger.casefold() in normalized_query for trigger in triggers if trigger
            )
            if not selected and not triggers:
                selected = (
                    skill.name.casefold() in normalized_query
                    or skill.description.casefold() in normalized_query
                )
            if not selected:
                continue
            if skill.load is None:
                continue
            instructions = skill.load().strip()
            if instructions:
                rendered.append(f"## Skill: {skill.name} (v{skill.version})\n\n{instructions}")
        return "\n\n".join(rendered)


__all__ = ["SkillRegistry"]
