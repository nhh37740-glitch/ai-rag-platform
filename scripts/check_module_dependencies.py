"""检查一级模块、中间模块和服务的依赖方向。"""
from __future__ import annotations

import ast
import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def violations(root: Path = ROOT) -> list[str]:
    schema = json.loads((root / "specifications/API_SCHEMA.json").read_text(encoding="utf-8"))
    domains = schema["domain_dependencies"]
    packages = {s["package"] for s in schema["modules"].values()} | {"core_specifications"}
    public = set(domains["public"])
    allowed = {}
    for domain in ("agent", "rag", "data"):
        for package in domains[domain]:
            allowed[package] = set(domains[domain]) | public
        facade = domain + "_facade"
        allowed[facade] = set(domains[domain]) | public
    # Cross-domain services are injected Protocols; even AGENT doesn't need concrete facades.
    failures = []
    # A public module may be consumed by every domain without consuming those
    # domains in return. Auth has the tighter core + stdlib contract explicitly.
    auth_imports = set(sys.stdlib_module_names) | {"core_specifications", "auth_runtime"}
    auth_project = root / "modules-src/auth-runtime/pyproject.toml"
    if auth_project.is_file():
        metadata = tomllib.loads(auth_project.read_text(encoding="utf-8"))
        for dependency in metadata.get("project", {}).get("dependencies", []):
            name = re.match(r"[A-Za-z0-9][A-Za-z0-9._-]*", dependency.strip())
            normalized = name.group().lower().replace("-", "_").replace(".", "_") if name else ""
            if normalized != "core_specifications":
                failures.append("modules-src/auth-runtime/pyproject.toml: auth_runtime 仅允许声明 core_specifications 依赖")
    graph = {package: set() for package in packages}
    files = []
    for mid, spec in schema["modules"].items():
        directory = root / "modules-src" / mid / spec["package"]
        files.extend((p, spec["package"]) for p in directory.rglob("*.py"))
    files.extend((p, "app") for p in (root / "apps/agent-server").glob("*.py"))
    files.extend((p, "core_specifications") for p in (root / "specifications/core_specifications").rglob("*.py"))
    for path, owner in files:
        allowed_imports = (set(domains["app"]) | public if owner == "app" else
                           set() if owner == "core_specifications" else allowed.get(owner, public))
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        importlib_aliases = {"importlib"}
        import_module_aliases = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                importlib_aliases.update(item.asname or item.name for item in node.names if item.name == "importlib")
            elif isinstance(node, ast.ImportFrom) and node.module == "importlib" and not node.level:
                import_module_aliases.update(item.asname or item.name for item in node.names if item.name == "import_module")
        for node in ast.walk(tree):
            imports = []
            if isinstance(node, ast.Import):
                imports = [item.name.partition(".")[0] for item in node.names]
            elif isinstance(node, ast.ImportFrom) and not node.level:
                imports = [(node.module or "").partition(".")[0]]
            elif isinstance(node, ast.ImportFrom) and owner == "auth_runtime" and node.level > 1:
                failures.append(f"{path.relative_to(root)}:{node.lineno}: auth_runtime 不允许导入父包")
            elif isinstance(node, ast.Call):
                func = node.func
                dynamic = (isinstance(func, ast.Name) and func.id in {"__import__"} | import_module_aliases) or (
                    isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name)
                    and func.value.id in importlib_aliases and func.attr == "import_module")
                argument = node.args[0] if node.args else next(
                    (keyword.value for keyword in node.keywords if keyword.arg == "name"), None
                )
                if dynamic:
                    if isinstance(argument, ast.Constant) and isinstance(argument.value, str) and not argument.value.startswith("."):
                        imports = [argument.value.partition(".")[0]]
                    elif owner == "auth_runtime":
                        failures.append(f"{path.relative_to(root)}:{node.lineno}: auth_runtime 动态导入必须使用静态绝对模块名")
            for package in imports:
                if owner in graph and package in packages and package != owner:
                    graph[owner].add(package)
                forbidden = package not in auth_imports if owner == "auth_runtime" else (
                    package in packages and package not in allowed_imports
                )
                if forbidden:
                    failures.append(f"{path.relative_to(root)}:{node.lineno}: {owner} 不允许依赖 {package}")
    visited = set()
    active = []
    def visit(package):
        if package in active:
            failures.append("模块循环依赖: " + " -> ".join(active[active.index(package):] + [package]))
            return
        if package in visited:
            return
        active.append(package)
        for dependency in sorted(graph[package]):
            visit(dependency)
        active.pop()
        visited.add(package)
    for package in sorted(graph):
        visit(package)
    return failures


if __name__ == "__main__":
    errors = violations()
    if errors:
        raise SystemExit("\n".join(errors))
    print("模块依赖检查通过")
