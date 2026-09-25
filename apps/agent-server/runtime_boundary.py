"""运行时边界：业务模块只允许从 artifacts 的编译产物加载。

项目约定源码（`modules-src/`）只用于编译和模块单测；集成侧运行时必须消费
`artifacts/<module-id>/<version>/` 里的 `.pyd/.so`。本模块在导入任何业务模块
之前执行，做三件事：

1. 读取 `registry.json`，确认每个 `published` 模块都有编译扩展；
2. 隔离运行环境——移除 editable 安装注入的 finder 与 `modules-src` 路径；
3. 提供 `assert_binary_runtime()`，在业务模块导入完成后校验它们的实际来源。

任何一步不满足都直接抛错，让服务启动失败，而不是悄悄退回源码模式。
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import sys
from pathlib import Path
from typing import Dict, Optional

ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = ROOT / "registry.json"
ARTIFACTS_DIR = ROOT / "artifacts"
SOURCE_DIR = ROOT / "modules-src"
CONTRACTS_DIR = ROOT / "contracts"

COMPILED_SUFFIXES = tuple(importlib.machinery.EXTENSION_SUFFIXES)


class RuntimeBoundaryError(RuntimeError):
    """运行时不满足二进制交付约束。"""


def _artifact_directory(spec: dict) -> Path:
    raw = str(spec.get("path", "")).replace("\\", "/")
    return (ROOT / raw).resolve()


def _find_compiled_init(package_directory: Path) -> Optional[Path]:
    if not package_directory.is_dir():
        return None
    for child in sorted(package_directory.iterdir()):
        if child.is_file() and child.name.startswith("__init__") and child.name.endswith(
            COMPILED_SUFFIXES
        ):
            return child
    return None


def load_published_modules() -> Dict[str, dict]:
    """返回 {包名: {module_id, version, directory, extension}}，只含已发布模块。"""
    if not REGISTRY_PATH.is_file():
        raise RuntimeBoundaryError(f"缺少 {REGISTRY_PATH}，无法确定运行时来源")
    try:
        registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeBoundaryError(f"registry.json 无法解析: {exc}") from exc

    modules: Dict[str, dict] = {}
    problems: list[str] = []
    for module_id, spec in (registry.get("modules") or {}).items():
        if not isinstance(spec, dict) or spec.get("status") != "published":
            continue
        package = spec.get("name")
        if not package:
            problems.append(f"{module_id}: registry 缺少 name")
            continue
        directory = _artifact_directory(spec)
        extension = _find_compiled_init(directory / package)
        if extension is None:
            problems.append(
                f"{module_id}: {directory / package} 下没有编译扩展，"
                f"请先运行 python scripts\\compile_extension_modules.py --module {module_id}"
            )
            continue
        modules[package] = {
            "module_id": module_id,
            "version": spec.get("version", ""),
            "directory": directory,
            "extension": extension,
        }

    if problems:
        raise RuntimeBoundaryError("二进制交付不完整:\n  - " + "\n  - ".join(problems))
    if not modules:
        raise RuntimeBoundaryError("registry.json 里没有任何 published 模块，拒绝启动")
    return modules


def _is_source_path(path: Path) -> bool:
    return path == SOURCE_DIR or SOURCE_DIR in path.parents


def _isolate(published: Dict[str, dict]) -> None:
    """阻断 editable 安装与 modules-src，把 artifacts 放到搜索路径最前。"""
    for package in published:
        if package in sys.modules:
            raise RuntimeBoundaryError(
                f"{package} 在建立运行边界之前已被导入，业务模块必须由 artifacts 首次加载"
            )

    blocked = [
        finder
        for finder in sys.meta_path
        if type(finder).__module__.startswith("__editable__")
    ]
    if blocked:
        sys.meta_path[:] = [finder for finder in sys.meta_path if finder not in blocked]

    kept_paths: list[str] = []
    for entry in sys.path:
        if not entry:
            kept_paths.append(entry)
            continue
        try:
            resolved = Path(entry).resolve()
        except OSError:
            kept_paths.append(entry)
            continue
        if _is_source_path(resolved):
            continue
        kept_paths.append(entry)
    sys.path[:] = kept_paths

    prefix = [str(CONTRACTS_DIR)]
    prefix.extend(str(item["directory"]) for item in published.values())
    for entry in reversed(prefix):
        while entry in sys.path:
            sys.path.remove(entry)
        sys.path.insert(0, entry)


def enforce_binary_runtime() -> Dict[str, dict]:
    """在导入业务模块之前调用；返回已发布的模块表供后续校验。"""
    published = load_published_modules()
    _isolate(published)
    return published


def _describe_violation(package: str, spec: dict, module_file: str) -> Optional[str]:
    if not module_file:
        return f"{package}: 没有 __file__，无法确认加载来源"
    path = Path(module_file)
    if not module_file.endswith(COMPILED_SUFFIXES):
        return f"{package}: 加载的是 {module_file}，不是编译扩展（禁止源码模式）"
    try:
        resolved = path.resolve()
    except OSError:
        return f"{package}: 无法解析 {module_file}"
    if spec["directory"] not in resolved.parents:
        return f"{package}: 加载自 {resolved}，不在 {spec['directory']} 内"
    return None


def assert_binary_runtime(published: Optional[Dict[str, dict]] = None) -> None:
    """在业务模块导入完成后调用，确认没有任何业务模块来自源码。

    已导入的模块必须来自 artifacts 的编译扩展；尚未导入的模块只做可解析性检查
    （不执行其代码），确认它们同样只能解析到 artifacts。
    """
    modules = published if published is not None else load_published_modules()
    problems: list[str] = []
    for package, spec in modules.items():
        module = sys.modules.get(package)
        if module is None:
            problem = _check_resolvable(package, spec)
            if problem:
                problems.append(problem)
            continue
        problem = _describe_violation(package, spec, getattr(module, "__file__", "") or "")
        if problem:
            problems.append(problem)

    for name, module in list(sys.modules.items()):
        module_file = getattr(module, "__file__", "") or ""
        if not module_file:
            continue
        try:
            resolved = Path(module_file).resolve()
        except OSError:
            continue
        if _is_source_path(resolved):
            problems.append(f"{name}: 从 modules-src 加载了源码 {resolved}")

    if problems:
        raise RuntimeBoundaryError("运行时不允许加载源码模块:\n  - " + "\n  - ".join(sorted(set(problems))))


def _check_resolvable(package: str, spec: dict) -> Optional[str]:
    """不执行模块代码，只确认该包在隔离后的环境里解析到 artifacts 的编译扩展。"""
    try:
        found = importlib.util.find_spec(package)
    except (ImportError, ValueError) as exc:
        return f"{package}: 无法解析（{type(exc).__name__}: {exc}）"
    if found is None:
        return f"{package}: 在 artifacts 中找不到该模块"
    return _describe_violation(package, spec, found.origin or "")


def main() -> None:
    published = enforce_binary_runtime()
    print(f"runtime boundary ok: {len(published)} published module(s)")
    for package, spec in sorted(published.items()):
        print(f"  {spec['module_id']}@{spec['version']}  ->  {spec['extension'].relative_to(ROOT)}")
    print(f"blocked source root: {SOURCE_DIR}")


if __name__ == "__main__":
    main()
