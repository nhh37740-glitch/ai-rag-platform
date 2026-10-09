from __future__ import annotations

from typing import Dict, List

from core_specifications import RequestContext, ToolDef

__version__ = "0.1.1"


def normalize_to_tool(mcp_tool: Dict) -> ToolDef:
    """把 MCP 工具定义统一成 ToolDef。兼容 {function:{...}} 或 {name,...} 两种形态。"""
    f = mcp_tool.get("function", mcp_tool)
    return ToolDef(
        name=f["name"],
        description=f.get("description", ""),
        parameters=f.get("parameters", {"type": "object"}),
    )


class McpServerClient:
    """与外部 MCP server 交互的客户端接口。v1 提供 MockClient。"""

    async def connect(self, name: str) -> None:
        self.name = name

    async def list_tools(self) -> List[ToolDef]:
        raise NotImplementedError

    async def call_tool(self, name: str, arguments: Dict) -> str:
        raise NotImplementedError


class MockClient(McpServerClient):
    _TOOLS = [
        {"function": {"name": "list_issues", "description": "查询历史 issue", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}}}},
        {"function": {"name": "create_issue", "description": "创建 issue", "parameters": {"type": "object", "properties": {"title": {"type": "string"}, "priority": {"type": "string"}}}}},
        {"function": {"name": "get_commits", "description": "查询最近 git 提交", "parameters": {"type": "object", "properties": {"repo": {"type": "string"}}}}},
    ]

    async def connect(self, name: str) -> None:
        self.name = name

    async def list_tools(self) -> List[ToolDef]:
        return [normalize_to_tool(t) for t in self._TOOLS]

    async def call_tool(self, name: str, arguments: Dict) -> str:
        if name == "list_issues":
            return '{"issues": ["#1142 网关 keep-alive 超时", "#1204 索引查询慢"]}'
        if name == "create_issue":
            return f'{{"created": true, "title": "{arguments.get("title", "")}", "priority": "{arguments.get("priority", "P2")}"}}'
        if name == "get_commits":
            return '{"commits": ["修复网关 keep-alive 超时", "更新 API 文档"]}'
        return '{"error": "unknown tool"}'


__all__ = ["McpServerClient", "MockClient", "normalize_to_tool"]
