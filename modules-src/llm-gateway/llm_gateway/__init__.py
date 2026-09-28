from __future__ import annotations

import json
from typing import AsyncIterator, List, Optional, Protocol

import httpx

from core_contracts import ChatMessage, RequestContext, ToolCall, ToolDef

__version__ = "0.1.0"


class LLMProvider(Protocol):
    async def generate(self, ctx: RequestContext, messages: List[ChatMessage], tools: Optional[List[ToolDef]] = None) -> tuple[str, List[ToolCall]]: ...
    async def stream(
        self,
        ctx: RequestContext,
        messages: List[ChatMessage],
        tools: Optional[List[ToolDef]] = None,
    ) -> AsyncIterator[str]: ...


class MockProvider:
    """离线演示/测试用：按用户输入关键词与工具列表，决定是回答问题还是调用工具。"""

    def __init__(self, scenario: str = "qa") -> None:
        self.scenario = scenario

    async def generate(self, ctx, messages, tools=None) -> tuple[str, list[ToolCall]]:
        user = _last_user(messages)
        has_tool_result = any(m.role == "tool" for m in messages)
        if tools and _wants_tool(user) and not has_tool_result:
            name = _tool_to_call(user, tools)
            if name:
                args = _tool_args(user, name)
                return "", [ToolCall("call_1", name, args)]
        if has_tool_result:
            return _last_tool(messages), []
        return _mock_answer(user, self.scenario), []

    async def stream(self, ctx, messages, tools=None) -> AsyncIterator[str]:
        text, calls = await self.generate(ctx, messages, tools)
        yield text


class DeepSeekProvider:
    """OpenAI 兼容的 DeepSeek 聊天 + 函数调用。"""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.deepseek.com",
        model: str = "deepseek-chat",
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.transport = transport

    async def generate(self, ctx, messages, tools=None) -> tuple[str, list[ToolCall]]:
        payload = {"model": self.model, "messages": [_m(m) for m in messages]}
        if tools:
            payload["tools"] = [{"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.parameters}} for t in tools]
            payload["tool_choice"] = "auto"
        async with httpx.AsyncClient(timeout=60, transport=self.transport) as client:
            r = await client.post(f"{self.base_url}/chat/completions", headers={"Authorization": f"Bearer {self.api_key}"}, json=payload)
            r.raise_for_status()
        data = r.json()
        choice = data["choices"][0]["message"]
        content = choice.get("content") or ""
        tool_calls = []
        for tc in choice.get("tool_calls") or []:
            try:
                args = json.loads(tc["function"]["arguments"] or "{}")
            except json.JSONDecodeError:
                args = {}
            tool_calls.append(ToolCall(tc.get("id", ""), tc["function"]["name"], args))
        return content, tool_calls

    async def stream(self, ctx, messages, tools=None) -> AsyncIterator[str]:
        text, _ = await self.generate(ctx, messages, tools)
        yield text


def _last_user(messages: List[ChatMessage]) -> str:
    for m in reversed(messages):
        if m.role == "user":
            return m.content
    return ""


def _last_tool(messages: List[ChatMessage]) -> str:
    for m in reversed(messages):
        if m.role == "tool":
            return m.content
    return ""


def _m(m: ChatMessage) -> dict:
    d = {"role": m.role, "content": m.content}
    if m.tool_calls:
        d["tool_calls"] = [
            {"id": tc.id, "type": "function", "function": {"name": tc.name, "arguments": json.dumps(tc.arguments, ensure_ascii=False)}}
            for tc in m.tool_calls
        ]
    if m.tool_call_id:
        d["tool_call_id"] = m.tool_call_id
    if m.name:
        d["name"] = m.name
    return d


def _wants_tool(user: str) -> bool:
    return any(k in user for k in ("建", "创建", "查", "commit", "issue", "Bug", "bug", "成员", "状态"))


def _tool_to_call(user: str, tools: List[ToolDef]) -> str:
    names = [t.name for t in tools]
    if any("issue" in n for n in names) and any(k in user for k in ("建", "创建", "Bug", "bug")):
        return next(n for n in names if "issue" in n)
    if any("commit" in n for n in names) and any(k in user for k in ("commit", "提交")):
        return next(n for n in names if "commit" in n)
    if any("member" in n for n in names) and any(k in user for k in ("成员", "谁")):
        return next(n for n in names if "member" in n)
    return names[0] if names else ""


def _tool_args(user: str, name: str) -> dict:
    if "issue" in name:
        return {"title": "P1 连接超时", "priority": "P1"}
    if "commit" in name:
        return {"repo": "demo", "since": "1d"}
    if "member" in name:
        return {"query": "后端"}
    return {"query": user}


def _mock_answer(user: str, scenario: str) -> str:
    if "认证" in user or "auth" in user.lower():
        return "在请求头带 `Authorization: Bearer <token>` 即可认证（见 API 文档第 3 节）。"
    if "故障" in user or "超时" in user:
        return "经检索，本周三 15:02 曾发生相似连接超时（issue #1142），根因是网关 keep-alive 过短；当前可复用的 SOP 已挂到知识库。"
    if "上次" in user or "处理到哪" in user:
        return "你上次正在排查 issue #1142，已定位到网关 keep-alive，尚未提交修复。"
    if "流程" in user or "怎么分析" in user:
        return "已按 bug-triage 技能流程给出分析。"
    return "（Mock 回答）已基于知识库检索与记忆给出结论。请接入 DEEPSEEK_API_KEY 后接入真实模型。"


__all__ = ["LLMProvider", "MockProvider", "DeepSeekProvider"]
