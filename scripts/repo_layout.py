"""模块源码目录布局。

模块源码按业务域分组存放：

    modules-src/<group>/<module-id>/

检查、测试、编译和打包脚本统一通过本模块定位模块目录，不再假设
``modules-src/*`` 的平铺布局。
"""
from __future__ import annotations

from pathlib import Path

# 每个模块只属于一个业务域；新增模块必须在这里登记，结构检查会拒绝
# 未登记或重复登记的目录。
MODULE_GROUPS: dict[str, tuple[str, ...]] = {
    "agent": (
        "agent-facade",
        "agent-runtime",
        "evaluation",
        "llm-gateway",
        "mcp-gateway",
        "mcp-servers",
        "skill-runtime",
        "tool-runtime",
    ),
    "rag": (
        "rag-facade",
        "rag-core",
        "rag-tools",
        "ingestion",
    ),
    "data": (
        "data-facade",
        "storage",
        "memory",
    ),
    "auth": (
        "auth-facade",
        "auth-runtime",
    ),
    "platform": (
        "observability",
    ),
}

GROUP_READERS: dict[str, str] = {
    "agent": "智能体编排、工具、技能、MCP 与模型网关",
    "rag": "检索增强生成：解析、分块、检索与 RAG 门面",
    "data": "持久化、向量/记忆存储与数据门面",
    "auth": "账号、会话与鉴权",
    "platform": "跨域可观测性与公共运行时设施",
}


def module_group(module_id: str) -> str:
    for group, members in MODULE_GROUPS.items():
        if module_id in members:
            return group
    raise KeyError(f"模块未登记业务域：{module_id}")


def module_dir(root: Path, module_id: str) -> Path:
    """返回 modules-src/<group>/<module-id>；未登记或目录缺失时抛错。"""
    path = root / "modules-src" / module_group(module_id) / module_id
    if not path.is_dir():
        raise FileNotFoundError(f"模块源码目录不存在：{path}")
    return path


def iter_module_dirs(root: Path) -> list[Path]:
    """按 MODULE_GROUPS 的稳定顺序返回已存在的模块目录。"""
    base = root / "modules-src"
    modules: list[Path] = []
    for group, members in MODULE_GROUPS.items():
        for module_id in members:
            path = base / group / module_id
            if path.is_dir():
                modules.append(path)
    return modules
