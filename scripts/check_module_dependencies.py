"""检查一级模块、中间模块和服务的依赖方向。"""
from __future__ import annotations

import ast
import json
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
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=str(path))):
            imports = []
            if isinstance(node, ast.Import):
                imports = [item.name.partition(".")[0] for item in node.names]
            elif isinstance(node, ast.ImportFrom) and not node.level:
                imports = [(node.module or "").partition(".")[0]]
            elif isinstance(node, ast.Call) and node.args:
                func = node.func
                dynamic = (isinstance(func, ast.Name) and func.id == "__import__") or (
                    isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name)
                    and func.value.id == "importlib" and func.attr == "import_module")
                if dynamic and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                    imports = [node.args[0].value.partition(".")[0]]
            for package in imports:
                if owner in graph and package in packages and package != owner:
                    graph[owner].add(package)
                if package in packages and package not in allowed_imports:
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
