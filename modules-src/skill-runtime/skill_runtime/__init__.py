from __future__ import annotations

import os
import re
from typing import Callable, Dict

from core_contracts import RequestContext, SkillDef

__version__ = "0.1.0"


class SkillRegistry:
    """扫描 skills/<name>/SKILL.md，命中后惰性加载指令。"""

    def __init__(self) -> None:
        self._skills: Dict[str, SkillDef] = {}
        self._root: str | None = None

    def load_dir(self, path: str) -> None:
        self._root = path
        if not os.path.isdir(path):
            return
        for entry in os.listdir(path):
            d = os.path.join(path, entry)
            md = os.path.join(d, "SKILL.md")
            if os.path.isdir(d) and os.path.isfile(md):
                name, desc, ver = self._parse_manifest(md)
                if not name:
                    name = entry
                self._skills[name] = SkillDef(name, desc or entry, ver or "0.1.0", self._loader(md))

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
    def _parse_manifest(md: str) -> tuple[str | None, str | None, str | None]:
        name = desc = ver = None
        with open(md, encoding="utf-8") as f:
            txt = f.read()
        m = re.search(r"(?m)^name:\s*(.+)$", txt)
        if m:
            name = m.group(1).strip()
        m = re.search(r"(?m)^description:\s*(.+)$", txt)
        if m:
            desc = m.group(1).strip()
        m = re.search(r"(?m)^version:\s*(.+)$", txt)
        if m:
            ver = m.group(1).strip()
        return name, desc, ver


__all__ = ["SkillRegistry"]
