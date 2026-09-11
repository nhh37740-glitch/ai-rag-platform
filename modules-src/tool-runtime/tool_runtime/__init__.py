from __future__ import annotations

import threading
from typing import Any, Callable, Dict

from core_contracts import RequestContext, ToolCall, ToolDef

__version__ = "0.2.0"


class ToolRegistry:
    """集中注册/执行 Agent 工具。每个工具是一个 (ToolDef, 可调用对象)。"""

    def __init__(self) -> None:
        self._tools: Dict[str, tuple[ToolDef, Callable[..., Any], bool]] = {}
        self._lock = threading.Lock()

    def register(
        self,
        t: ToolDef,
        fn: Callable[..., Any],
        context_aware: bool = False,
    ) -> None:
        """注册工具；上下文参数只在执行期注入，不属于公开工具参数。"""
        with self._lock:
            self._tools[t.name] = (t, fn, context_aware)

    def list(self, ctx: RequestContext | None = None) -> list[ToolDef]:
        with self._lock:
            return [t for t, _, _ in self._tools.values()]

    def execute(
        self,
        ctx: RequestContext,
        call: ToolCall,
        runtime_context: dict | None = None,
    ) -> str:
        with self._lock:
            item = self._tools.get(call.name)
        if item is None:
            return f"ERROR: unknown tool {call.name}"
        _, fn, context_aware = item
        try:
            arguments = dict(call.arguments)
            if context_aware:
                # 调用方不能通过工具参数伪造运行上下文。
                arguments["ctx"] = ctx
                arguments["runtime_context"] = runtime_context
            result = fn(**arguments)
            return str(result)
        except Exception as e:  # 工具失败以字符串返回给 LLM，不中断会话
            return f"ERROR: {type(e).__name__}: {e}"


_GLOBAL = ToolRegistry()


def tool(
    name: str,
    description: str,
    parameters: dict,
    context_aware: bool = False,
) -> Callable:
    def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
        _GLOBAL.register(
            ToolDef(name, description, parameters),
            fn,
            context_aware=context_aware,
        )
        return fn

    return deco


def default_registry() -> ToolRegistry:
    return _GLOBAL


__all__ = ["ToolRegistry", "tool", "default_registry"]
