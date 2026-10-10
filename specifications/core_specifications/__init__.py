from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Protocol, runtime_checkable


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


@dataclass(frozen=True)
class IngestResult:
    source_id: str
    knowledge_base_id: str
    chunk_count: int


@runtime_checkable
class VectorStore(Protocol):
    def add(self, source_id: str, chunks: List[str], embeddings: Any) -> None: ...
    def search(self, embedding: Any, top_k: int = 5, scopes: Optional[List[str]] = None) -> List[tuple[str, str, float]]: ...
    def list_documents(self, scopes: Optional[List[str]] = None) -> List[tuple[str, int]]: ...
    def document_chunks(self, source_id: str) -> List[str]: ...


@runtime_checkable
class MemoryStorePort(Protocol):
    def get(self, ctx: RequestContext, namespace: str, key: str) -> Optional[MemoryEntry]: ...
    def write(self, ctx: RequestContext, namespace: str, key: str, content: str, importance: float = 0.0) -> MemoryEntry: ...
    def search(self, ctx: RequestContext, namespace: str, query: str, top_k: int = 5) -> List[MemoryEntry]: ...
    def forget(self, ctx: RequestContext, namespace: str, key: str) -> None: ...


@runtime_checkable
class LLMProviderPort(Protocol):
    async def generate(self, ctx: RequestContext, messages: List[ChatMessage], tools: Optional[List[ToolDef]] = None) -> tuple[str, List[ToolCall]]: ...
    def stream(self, ctx: RequestContext, messages: List[ChatMessage], tools: Optional[List[ToolDef]] = None) -> AsyncIterator[str]: ...


@runtime_checkable
class TraceStorePort(Protocol):
    def record(self, span: SpanEvent) -> None: ...
    def get(self, trace_id: str) -> List[SpanEvent]: ...


@runtime_checkable
class StateStorePort(Protocol):
    def get(self, ctx: RequestContext, key: str) -> Any: ...
    def set(self, ctx: RequestContext, key: str, value: Any) -> None: ...
    def delete(self, ctx: RequestContext, key: str) -> None: ...


@runtime_checkable
class DataServicePort(Protocol):
    def initialize(self, ctx: RequestContext) -> None: ...
    def memory_store(self, ctx: RequestContext) -> MemoryStorePort: ...
    def vector_store(self, ctx: RequestContext) -> VectorStore: ...
    def state_db(self, ctx: RequestContext) -> StateStorePort: ...
    def close(self, ctx: RequestContext) -> None: ...


@runtime_checkable
class RagServicePort(Protocol):
    def tool_definitions(self, ctx: RequestContext) -> List[ToolDef]: ...
    def execute_tool(self, ctx: RequestContext, call: ToolCall, knowledge_base_ids: List[str]) -> str: ...
    def search(self, ctx: RequestContext, query: str, knowledge_base_ids: List[str], top_k: Optional[int] = None, mode: str = "vector") -> RetrievalResult: ...
    def list_documents(self, ctx: RequestContext, knowledge_base_ids: List[str]) -> List[dict]: ...
    def read_document(self, ctx: RequestContext, source_id: str, knowledge_base_ids: List[str], offset: int = 0, max_chunks: Optional[int] = None) -> RetrievalResult: ...
    def parse_document(self, ctx: RequestContext, path: str, title: str = "") -> str: ...
    def split_text(self, ctx: RequestContext, text: str) -> List[str]: ...
    def embed_texts(self, ctx: RequestContext, texts: List[str]) -> List[List[float]]: ...
    def ingest(self, ctx: RequestContext, path: str, knowledge_base_id: str, source_id: str = "") -> IngestResult: ...
    def ingest_markdown(self, ctx: RequestContext, markdown: str, source_id: str) -> IngestResult: ...


__all__ += ["IngestResult", "VectorStore", "MemoryStorePort", "LLMProviderPort", "TraceStorePort", "StateStorePort", "DataServicePort", "RagServicePort"]


@dataclass(frozen=True)
class AuthPrincipal:
    """Server-issued identity; proof must never be serialized into HTTP or traces."""
    user_id: str
    role: str
    proof: str = field(default="", repr=False)


@runtime_checkable
class AuthServicePort(Protocol):
    def guest(self, ctx: RequestContext) -> AuthPrincipal: ...
    def authenticate_proxy(self, ctx: RequestContext, proxy_token: str, user_id: str, role: str) -> AuthPrincipal: ...
    def authorize(self, ctx: RequestContext, principal: AuthPrincipal, permission: str) -> None: ...
    def allowed_notebooks(self, ctx: RequestContext, principal: AuthPrincipal, available_ids: List[str], public_ids: List[str]) -> List[str]: ...


__all__ += ["AuthPrincipal", "AuthServicePort"]
