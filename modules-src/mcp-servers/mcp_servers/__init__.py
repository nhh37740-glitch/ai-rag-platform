from __future__ import annotations

import json
from typing import Callable, Dict, List

__version__ = "0.1.0"


class MockMcpServer:
    """mock 外部系统 connector：注册工具，以 tools/list 与 tools/call 暴露。"""

    def __init__(self) -> None:
        self._tools: Dict[str, tuple[str, str, dict, Callable]] = {}

    def register(self, name: str, description: str, parameters: dict, handler: Callable) -> None:
        self._tools[name] = (name, description, parameters, handler)

    def tools(self) -> List[dict]:
        return [{"name": name, "description": desc, "parameters": params} for name, desc, params, _ in self._tools.values()]

    def call(self, name: str, arguments: dict) -> dict:
        item = self._tools.get(name)
        if item is None:
            return {"error": f"unknown tool {name}"}
        _, _, _, handler = item
        try:
            return {"result": handler(**arguments)}
        except Exception as e:
            return {"error": f"{type(e).__name__}: {e}"}


def build_default_server() -> MockMcpServer:
    s = MockMcpServer()
    s.register("list_issues", "查询历史 issue", {"type": "object", "properties": {"query": {"type": "string"}}}, lambda query="": ["#1142 网关 keep-alive 超时", "#1204 索引慢"])
    s.register("create_issue", "创建 issue", {"type": "object", "properties": {"title": {"type": "string"}, "priority": {"type": "string"}}, "required": ["title"]}, lambda title, priority="P2": {"id": "ISSUE-12004", "title": title, "priority": priority})
    s.register("get_commits", "查询最近提交", {"type": "object", "properties": {"repo": {"type": "string"}}, "required": ["repo"]}, lambda repo="demo": ["修复 keep-alive", "更新文档"])
    return s


__all__ = ["MockMcpServer", "build_default_server"]
