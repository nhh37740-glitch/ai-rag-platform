from __future__ import annotations

import threading
from typing import Callable, Dict

from core_contracts import RequestContext, ToolCall, ToolDef

__version__ = "0.1.0"


class ToolRegistry:
    """集中注册/执行 Agent 工具。每个工具是一个 (ToolDef, 可调用对象)。"""

    def __init__(self) -> None:
        self._tools: Dict[str, tuple[ToolDef, Callable]] = {}
        self._lock = threading.Lock()

    def register(self, t: ToolDef, fn: Callable) -> None:
        with self._lock:
            self._tools[t.name] = (t, fn)

    def list(self, ctx: RequestContext | None = None) -> list[ToolDef]:
        with self._lock:
            return [t for t, _ in self._tools.values()]

    def execute(self, ctx: RequestContext, call: ToolCall) -> str:
        with self._lock:
            item = self._tools.get(call.name)
        if item is None:
            return f"ERROR: unknown tool {call.name}"
        _, fn = item
        try:
            result = fn(**call.arguments)
            return str(result)
        except Exception as e:  # 工具失败以字符串返回给 LLM，不中断会话
            return f"ERROR: {type(e).__name__}: {e}"


_GLOBAL = ToolRegistry()


def tool(name: str, description: str, parameters: dict) -> Callable:
    def deco(fn: Callable) -> Callable:
        _GLOBAL.register(ToolDef(name, description, parameters), fn)
        return fn

    return deco


def default_registry() -> ToolRegistry:
    return _GLOBAL


__all__ = ["ToolRegistry", "tool", "default_registry"]
