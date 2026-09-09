from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


@dataclass(frozen=True)
class RequestContext:
    """贯穿所有模块的调用上下文。trace_id 用于跨模块全链路追踪。"""

    trace_id: str
    request_id: str
    user_id: str = ""
    session_id: str = ""


@dataclass
class ChatMessage:
    role: str  # system | user | assistant | tool
    content: str = ""
    tool_call_id: str = ""
    name: str = ""
    tool_calls: List[ToolCall] = field(default_factory=list)


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: Dict[str, Any]


@dataclass
class ToolDef:
    name: str
    description: str
    parameters: Dict[str, Any]  # JSON Schema


@dataclass
class Citation:
    source_id: str
    title: str
    text: str
    score: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RetrievalResult:
    query: str
    contexts: List[str] = field(default_factory=list)
    citations: List[Citation] = field(default_factory=list)


@dataclass
class MemoryEntry:
    id: str
    namespace: str  # session | user
    key: str
    content: str
    created: str
    importance: float = 0.0


@dataclass
class SkillDef:
    name: str
    description: str
    version: str = "0.1.0"
    load: Optional[Callable[[], str]] = None  # 惰性加载完整指令


@dataclass
class SpanEvent:
    trace_id: str
    span: str
    start_ns: int
    end_ns: int
    status: str = "ok"  # ok | error
    error: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)


__all__ = [
    "RequestContext",
    "ChatMessage",
    "ToolCall",
    "ToolDef",
    "Citation",
    "RetrievalResult",
    "MemoryEntry",
    "SkillDef",
    "SpanEvent",
]
