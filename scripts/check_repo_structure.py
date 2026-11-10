"""检查仓库目录层级、模块归属和导航文档。

目标：顶层只保留稳定层级；模块源码按业务域分组；构建产物只出现在
``artifacts/``；每个重要目录都有可读的导航说明。新增目录或模块时，
先更新 ``scripts/repo_layout.py``、本文件和 ``docs/CODE_TREE.md``。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from repo_layout import MODULE_GROUPS

ROOT = Path(__file__).resolve().parents[1]

TOP_LEVEL_ALLOWED = {
    ".dockerignore",
    ".env.example",
    ".gitattributes",
    ".gitignore",
    "AGENTS.md",
    "CLAUDE.md",
    "Dockerfile",
    "Jenkinsfile",
    "README.md",
    "apps",
    "artifacts",
    "compose.yaml",
    "data",
    "docs",
    "modules-src",
    "pytest.ini",
    "registry.json",
    "requirements-build.txt",
    "requirements-runtime.txt",
    "scripts",
    "skills",
    "specifications",
}

TOP_LEVEL_IGNORED = {
    ".git",
    ".github",
    ".idea",
    ".pytest_cache",
    ".venv",
    ".vscode",
    "__pycache__",
    "dist",
    "reports",
}

MODULE_FILES = (
    "API_SCHEMA.json",
    "CHANGELOG.md",
    "INTERFACE.md",
    "README.md",
    "VERSION",
    "pyproject.toml",
)

NAVIGATION_FILES = (
    "CLAUDE.md",
    "docs/CODE_TREE.md",
    "modules-src/README.md",
    "artifacts/README.md",
    "apps/README.md",
    "scripts/README.md",
    "specifications/README.md",
)


def _check_top_level(root: Path) -> list[str]:
    errors = []
    for entry in sorted(root.iterdir()):
        name = entry.name
        if name in TOP_LEVEL_ALLOWED or name in TOP_LEVEL_IGNORED or name.startswith(".env"):
            continue
        errors.append(
            f"未登记的顶层条目：{name}；请先登记到 check_repo_structure.py 和 docs/CODE_TREE.md"
        )
    return errors


def _check_modules(root: Path) -> list[str]:
    errors = []
    schema_path = root / "specifications/API_SCHEMA.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    schema_modules = schema.get("modules", {})

    registered: dict[str, str] = {}
    for group, members in MODULE_GROUPS.items():
        for module_id in members:
            if module_id in registered:
                errors.append(f"模块重复登记：{module_id} 同时属于 {registered[module_id]} 和 {group}")
            registered[module_id] = group
    missing = sorted(set(schema_modules) - set(registered))
    extra = sorted(set(registered) - set(schema_modules))
    if missing:
        errors.append("API_SCHEMA 中的模块未登记业务域：" + ", ".join(missing))
    if extra:
        errors.append("业务域中登记了 API_SCHEMA 不存在的模块：" + ", ".join(extra))

    base = root / "modules-src"
    if not base.is_dir():
        return errors + ["缺少 modules-src/"]
    for entry in sorted(base.iterdir()):
        if entry.name.startswith(".") or entry.is_file():
            continue
        if entry.name not in MODULE_GROUPS:
            errors.append(f"modules-src/{entry.name} 不是已登记的业务域目录")

    for group, members in MODULE_GROUPS.items():
        group_dir = base / group
        if not group_dir.is_dir():
            errors.append(f"缺少业务域目录：modules-src/{group}/")
            continue
        readme = group_dir / "README.md"
        if not readme.is_file():
            errors.append(f"缺少业务域导航：modules-src/{group}/README.md")
        actual = {path.name for path in group_dir.iterdir() if path.is_dir()}
        for module_id in sorted(set(members) - actual):
            errors.append(f"缺少模块目录：modules-src/{group}/{module_id}/")
        for module_id in sorted(actual - set(members)):
            errors.append(f"未登记的模块目录：modules-src/{group}/{module_id}/")

        for module_id in members:
            module_path = group_dir / module_id
            if not module_path.is_dir():
                continue
            for filename in MODULE_FILES:
                if not (module_path / filename).is_file():
                    errors.append(f"缺少文件：{module_path.relative_to(root)}/{filename}")
            package = module_id.replace("-", "_")
            if not (module_path / package).is_dir():
                errors.append(f"缺少包目录：{module_path.relative_to(root)}/{package}/")
            if not (module_path / "tests").is_dir():
                errors.append(f"缺少模块测试：{module_path.relative_to(root)}/tests/")
            version_file = module_path / "VERSION"
            if version_file.is_file():
                version = version_file.read_text(encoding="utf-8").strip()
                expected = schema_modules.get(module_id, {}).get("version")
                if expected and version != expected:
                    errors.append(
                        f"版本不一致：{module_path.relative_to(root)}/VERSION={version}，"
                        f"API_SCHEMA={expected}"
                    )
    return errors


def _check_artifacts(root: Path) -> list[str]:
    errors = []
    registry_path = root / "registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    modules = registry.get("modules", {})
    artifacts = root / "artifacts"
    if not artifacts.is_dir():
        return ["缺少 artifacts/ 发布产物目录"]
    for module_id, spec in modules.items():
        relative = str(spec.get("path", "")).replace("\\", "/")
        if relative != f"artifacts/{module_id}/{spec.get('version')}":
            errors.append(f"registry 路径不符合 artifacts/<module>/<version>：{module_id} -> {relative}")
            continue
        path = root / relative
        if not path.is_dir():
            errors.append(f"registry 指向的产物目录不存在：{relative}")
            continue
        for filename in ("VERSION", "checksum.sha256", "INTERFACE.md", "API_SCHEMA.json"):
            if not (path / filename).is_file():
                errors.append(f"产物缺少 {filename}：{relative}")
        if not (path / str(spec.get("name", ""))).is_dir():
            errors.append(f"产物缺少包目录 {spec.get('name')}：{relative}")
    known = set(modules)
    for entry in sorted(artifacts.iterdir()):
        if entry.is_dir() and entry.name not in known:
            errors.append(f"artifacts/{entry.name} 未登记到 registry.json")
    return errors


def _check_navigation(root: Path) -> list[str]:
    errors = []
    for relative in NAVIGATION_FILES:
        if not (root / relative).is_file():
            errors.append(f"缺少导航文档：{relative}")
    return errors


def check(root: Path = ROOT) -> list[str]:
    errors = []
    errors.extend(_check_top_level(root))
    errors.extend(_check_modules(root))
    errors.extend(_check_artifacts(root))
    errors.extend(_check_navigation(root))
    return errors


def main() -> None:
    errors = check()
    if errors:
        print("仓库结构检查失败：")
        for error in errors:
            print(f"  - {error}")
        raise SystemExit(1)
    print(
        f"仓库结构检查通过：{len(MODULE_GROUPS)} 个业务域，"
        f"{sum(len(members) for members in MODULE_GROUPS.values())} 个模块"
    )


if __name__ == "__main__":
    main()
