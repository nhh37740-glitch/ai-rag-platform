from __future__ import annotations

import argparse
import importlib.machinery
import json
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "modules-src"
ART = ROOT / "artifacts"
SCHEMA = ROOT / "specifications" / "API_SCHEMA.json"


def compiled_init_files(package_dir: Path) -> list[Path]:
    """Return this platform's compiled package entrypoints after cythonize -i."""
    suffixes = tuple(importlib.machinery.EXTENSION_SUFFIXES)
    return sorted(
        path
        for path in package_dir.iterdir()
        if path.is_file()
        and path.name.startswith("__init__")
        and path.name.endswith(suffixes)
    )


def _select_modules(requested: list[str]) -> set[str] | None:
    """把 --module 参数解析成模块目录名集合；为空表示编译全部。"""
    if not requested:
        return None
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    alias: dict[str, str] = {}
    for module_id, spec in schema.get("modules", {}).items():
        alias[module_id] = module_id
        package = spec.get("package")
        if package:
            alias[package] = module_id
            alias[package.replace("_", "-")] = module_id
    selected: set[str] = set()
    unknown: list[str] = []
    for item in requested:
        module_id = alias.get(item.strip())
        if module_id is None:
            unknown.append(item)
        else:
            selected.add(module_id)
    if unknown:
        raise SystemExit(
            "未知模块: " + ", ".join(unknown) + "；可用模块: " + ", ".join(sorted(alias))
        )
    return selected


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="把 modules-src 下的模块编译成二进制工件。默认编译全部模块。"
    )
    parser.add_argument(
        "--module",
        action="append",
        default=[],
        metavar="ID",
        help="只编译指定模块（模块 ID 或包名，如 rag-core / rag_core），可重复传入。",
    )
    args = parser.parse_args(argv)
    selected = _select_modules(args.module)

    built = 0
    skipped = 0
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    module_ids = {
        spec["package"]: module_id
        for module_id, spec in schema.get("modules", {}).items()
    }
    for mod in sorted(SRC.iterdir()):
        py = mod / "pyproject.toml"
        if not py.exists():
            continue
        with open(py, "rb") as f:
            proj = tomllib.load(f).get("project", {})
        name = proj.get("name")
        version = proj.get("version", "0.1.0")
        if not name:
            continue
        pkg = name.replace("-", "_")
        module_id = module_ids.get(pkg)
        if module_id is None:
            continue
        if selected is not None and module_id not in selected:
            skipped += 1
            continue
        init = mod / pkg / "__init__.py"
        if not init.exists():
            continue
        print(f"[cythonize] {pkg}@{version}")
        subprocess.run([sys.executable, "-m", "Cython.Build.Cythonize", "-i", str(init)], cwd=ROOT, check=True)
        out = ART / module_id / version / pkg
        out.mkdir(parents=True, exist_ok=True)
        compiled = compiled_init_files(mod / pkg)
        if not compiled:
            raise RuntimeError(f"{pkg}: cythonize did not produce a compiled extension")
        for extension in compiled:
            shutil.copy2(extension, out / extension.name)
        built += 1
    if skipped:
        print(f"skipped {skipped} unselected module(s)")
    print(f"built {built} compiled packages under artifacts/<module-id>/<version>/<pkg>/")


if __name__ == "__main__":
    main()
