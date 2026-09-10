from __future__ import annotations

import hashlib
import json
import os
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "modules-src"
ARTIFACTS = ROOT / "artifacts"
REGISTRY = ROOT / "registry.json"
SCHEMA = ROOT / "contracts" / "API_SCHEMA.json"


def sha256_tree(d: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(d.rglob("*")):
        if (
            p.is_file()
            and "__pycache__" not in p.parts
            and ".egg-info" not in p.parts
            and p.suffix not in (".c", ".pyd", ".so", ".pyc")
        ):
            h.update(str(p.relative_to(d)).encode("utf-8"))
            h.update(p.read_bytes())
    return h.hexdigest()


def read_any(p: Path) -> str:
    for enc in ("utf-8", "gbk"):
        try:
            return p.read_text(encoding=enc)
        except UnicodeDecodeError:
            continue
    return p.read_text(encoding="utf-8", errors="replace")


def read_pyproject(d: Path) -> dict | None:
    py = d / "pyproject.toml"
    if not py.exists():
        return None
    with open(py, "rb") as f:
        data = tomllib.load(f)
    return data.get("project", {})


def main() -> None:
    modules: dict = {}
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    module_ids = {
        spec["package"]: module_id
        for module_id, spec in schema.get("modules", {}).items()
    }
    for mod_dir in sorted(SRC.iterdir()):
        if not (mod_dir / "pyproject.toml").exists():
            continue
        proj = read_pyproject(mod_dir) or {}
        name = proj.get("name")
        version = proj.get("version", "0.1.0")
        if not name:
            continue
        pkg = name.replace("-", "_")
        module_id = module_ids.get(pkg)
        if module_id is None:
            continue
        if not (mod_dir / pkg / "__init__.py").exists():
            continue  # 跳过仅有脚手架无扁平实现目录
        out = ARTIFACTS / module_id / version
        out.mkdir(parents=True, exist_ok=True)
        (out / "VERSION").write_text(version + "\n", encoding="utf-8")
        (out / "INTERFACE.md").write_text(read_any(mod_dir / "INTERFACE.md") if (mod_dir / "INTERFACE.md").exists() else "", encoding="utf-8")
        (out / "API_SCHEMA.json").write_text(
            json.dumps({"module": pkg, "version": version, "public_api": _exports(mod_dir, pkg)}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (out / "CHANGELOG.md").write_text(f"# {pkg}\n\n## {version}\n- 初版实现（离线标准库/httpx/numpy）。\n", encoding="utf-8")
        (out / "test_contract.py").write_text(_contract_test(pkg), encoding="utf-8")
        checksum = sha256_tree(mod_dir)
        (out / "checksum.sha256").write_text(checksum + "  " + name + "\n", encoding="utf-8")
        has_binary = any(out.rglob("*.pyd")) or any(out.rglob("*.so")) or any(out.rglob("*.exe"))
        modules[module_id] = {
            "name": pkg,
            "version": version,
            "checksum": checksum,
            "path": str(out.relative_to(ROOT)),
            "status": "published" if has_binary else "contract-only",
        }
    REGISTRY.write_text(json.dumps({"format": 1, "modules": modules}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"artifacts registered for {len(modules)} modules")
    for pkg, info in modules.items():
        print(f"  {pkg}@{info['version']}  {info['checksum'][:12]}")


def _exports(mod_dir: Path, pkg: str) -> list[str]:
    init = mod_dir / pkg / "__init__.py"
    if not init.exists():
        return []
    txt = read_any(init)
    if "__all__" in txt:
        import re

        m = re.search(r"__all__\s*=\s*\[(.*?)\]", txt, re.S)
        if m:
            return re.findall(r'"([^"]+)"|[^"]*?([A-Za-z_]\w*)', m.group(1))
    return [l.split("(")[0].strip() for l in txt.splitlines() if l.startswith("def ") or l.startswith("class ")]


def _contract_test(pkg: str) -> str:
    return (
        "import importlib\n"
        "import unittest\n\n"
        f"class Contract(unittest.TestCase):\n"
        f"    def test_import(self):\n"
        f"        m = importlib.import_module('{pkg}')\n"
        f"        self.assertTrue(hasattr(m, '__version__'))\n\n"
        "if __name__ == '__main__':\n"
        "    unittest.main()\n"
    )


if __name__ == "__main__":
    main()
