# cython: annotation_typing=False
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import List, Optional

from core_specifications import (
    Citation, IngestResult, RequestContext, RetrievalResult, SpanEvent,
    ToolCall, ToolDef, TraceStorePort, VectorStore,
)
from ingestion import SUPPORTED_EXTENSIONS, chunk, parse, to_markdown
from rag_core import DEFAULT_READ_CHUNKS, MAX_READ_CHUNKS, embed
from rag_tools import RagTools

__version__ = "0.1.0"
__all__ = ["RagService"]

_SEARCH_MODES = {
    "vector": "search_knowledge_base",
    "hybrid": "hybrid_search_knowledge_base",
    "keyword": "keyword_search_knowledge_base",
}
_LIST_TOOL = "list_knowledge_documents"
_READ_TOOL = "read_knowledge_document"
_SEARCH_TOOLS = frozenset(_SEARCH_MODES.values())


def _integer(value: int, name: str, minimum: int, maximum: Optional[int] = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} 必须是整数")
    if value < minimum or (maximum is not None and value > maximum):
        raise ValueError(f"{name} 超出允许范围")
    return value


def _text(value: str, name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} 必须是字符串")
    value = value.strip()
    if not value:
        raise ValueError(f"{name} 不能为空")
    return value


def _identifier(value: str, name: str) -> str:
    value = _text(value, name)
    if value in (".", "..") or any(c in value for c in "/\\:\x00"):
        raise ValueError(f"{name} 不允许路径穿越或目录分隔符")
    return value


def _source(value: str) -> str:
    value = _text(value, "source_id")
    parts = value.split("/")
    if len(parts) != 2:
        raise ValueError("source_id 必须为 <knowledge_base_id>/<document_id>")
    return "/".join(_identifier(part, "source_id") for part in parts)


def _scope(values: List[str]) -> List[str]:
    if not isinstance(values, list):
        raise TypeError("knowledge_base_ids 必须是字符串列表")
    return list(dict.fromkeys(_identifier(value, "knowledge_base_id") for value in values))


def _retrieval(payload: dict) -> RetrievalResult:
    citations = [Citation(**item) for item in payload["citations"]]
    return RetrievalResult(
        query=payload["query"], contexts=[item.text for item in citations], citations=citations,
    )


class RagService:
    """RAG domain facade; all persistence is provided through VectorStore."""

    def __init__(self, store: VectorStore, tracing: TraceStorePort, top_k: int = 5) -> None:
        self.store = store
        self.tracing = tracing
        self.top_k = _integer(top_k, "top_k", 1, 20)
        self._tools = RagTools(store, tracing, self.top_k)

    def tool_definitions(self, ctx: RequestContext) -> List[ToolDef]:
        return self._tools.tool_definitions()

    def execute_tool(self, ctx: RequestContext, call: ToolCall, knowledge_base_ids: List[str]) -> str:
        # The model controls arguments only; injected context and scope always win.
        return self._execute(ctx, call.name, call.arguments, knowledge_base_ids)

    def search(
        self, ctx: RequestContext, query: str, knowledge_base_ids: List[str],
        top_k: Optional[int] = None, mode: str = "vector",
    ) -> RetrievalResult:
        if not isinstance(mode, str) or mode not in _SEARCH_MODES:
            error = ValueError("mode 只支持 vector/hybrid/keyword")
            self._record(ctx, "search", knowledge_base_ids, time.perf_counter_ns(), error=error)
            raise error
        return _retrieval(json.loads(self._execute(
            ctx, _SEARCH_MODES[mode], {"query": query, "top_k": top_k}, knowledge_base_ids,
        )))

    def list_documents(self, ctx: RequestContext, knowledge_base_ids: List[str]) -> List[dict]:
        return json.loads(self._execute(ctx, _LIST_TOOL, {}, knowledge_base_ids))["documents"]

    def read_document(
        self, ctx: RequestContext, source_id: str, knowledge_base_ids: List[str],
        offset: int = 0, max_chunks: Optional[int] = None,
    ) -> RetrievalResult:
        return _retrieval(json.loads(self._execute(ctx, _READ_TOOL, {
            "source_id": source_id, "offset": offset, "max_chunks": max_chunks,
        }, knowledge_base_ids)))

    def parse_document(self, ctx: RequestContext, path: str, title: str = "") -> str:
        path = _text(path, "path")
        if Path(path).suffix.lower() not in SUPPORTED_EXTENSIONS:
            raise ValueError("不支持的文件类型")
        # Check extracted body before ingestion adds a synthetic heading to empty md.
        if not any(section.strip() for section in parse(path)):
            raise ValueError("文件中没有可提取的文本")
        return to_markdown(path, title)

    def split_text(self, ctx: RequestContext, text: str) -> List[str]:
        text = _text(text, "text")
        return chunk([part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()])

    def embed_texts(self, ctx: RequestContext, texts: List[str]) -> List[List[float]]:
        if not isinstance(texts, list):
            raise TypeError("texts 必须是字符串列表")
        normalized = [_text(text, "text") for text in texts]
        if not normalized:
            return []
        return [list(map(float, vector)) for vector in embed(normalized)]

    def ingest(
        self, ctx: RequestContext, path: str, knowledge_base_id: str, source_id: str = "",
    ) -> IngestResult:
        path = _text(path, "path")
        knowledge_base_id = _identifier(knowledge_base_id, "knowledge_base_id")
        if not isinstance(source_id, str):
            raise TypeError("source_id 必须是字符串")
        source_id = _source(source_id or f"{knowledge_base_id}/{Path(path).stem}")
        if source_id.partition("/")[0] != knowledge_base_id:
            raise ValueError("source_id 与 knowledge_base_id 不匹配")
        return self.ingest_markdown(ctx, self.parse_document(ctx, path), source_id)

    def ingest_markdown(self, ctx: RequestContext, markdown: str, source_id: str) -> IngestResult:
        start_ns = time.perf_counter_ns()
        scopes: List[str] = []
        try:
            source_id = _source(source_id)
            scopes = [source_id.partition("/")[0]]
            chunks = self.split_text(ctx, markdown)
            self.store.add(source_id, chunks, self.embed_texts(ctx, chunks))
            result = IngestResult(source_id, scopes[0], len(chunks))
        except Exception as error:
            self._record(ctx, "ingest_markdown", scopes, start_ns, error=error)
            raise
        self._record(ctx, "ingest_markdown", scopes, start_ns, source_id=source_id, chunk_count=len(chunks))
        return result

    def _execute(self, ctx: RequestContext, name: str, arguments: dict, knowledge_base_ids: List[str]) -> str:
        start_ns = time.perf_counter_ns()
        scope: List[str] = []
        try:
            scope = _scope(knowledge_base_ids)
            if name not in _SEARCH_TOOLS and name not in (_LIST_TOOL, _READ_TOOL):
                raise ValueError(f"未知 RAG 工具: {name}")
            if not isinstance(arguments, dict):
                raise TypeError("arguments 必须是字典")
            args = {key: value for key, value in arguments.items()
                    if key not in ("knowledge_base_ids", "ctx", "runtime_context")}
            allowed = ({"query", "top_k"} if name in _SEARCH_TOOLS else
                       {"source_id", "offset", "max_chunks"} if name == _READ_TOOL else set())
            if args.keys() - allowed:
                raise ValueError("工具包含未知参数")
            if name in _SEARCH_TOOLS:
                query = _text(args.get("query"), "query")
                limit = self.top_k if args.get("top_k") is None else _integer(args["top_k"], "top_k", 1, 20)
            elif name == _READ_TOOL:
                source_id = _source(args.get("source_id"))
                offset = _integer(args.get("offset", 0), "offset", 0)
                limit = DEFAULT_READ_CHUNKS if args.get("max_chunks") is None else _integer(
                    args["max_chunks"], "max_chunks", 1, MAX_READ_CHUNKS,
                )
                if source_id.partition("/")[0] not in scope:
                    raise ValueError("source_id 不在当前知识库范围内")
        except Exception as error:
            self._record(ctx, name, scope, start_ns, error=error)
            raise
        if name in _SEARCH_TOOLS:
            if not scope:
                # Empty selection never starts embedding/model download.
                self._record(ctx, name, scope, start_ns, query=query, hit_count=0, hits=[])
                return json.dumps({"tool": name, "query": query, "hit_count": 0, "citations": []}, ensure_ascii=False)
            method = {"search_knowledge_base": self._tools.search,
                      "hybrid_search_knowledge_base": self._tools.hybrid_search,
                      "keyword_search_knowledge_base": self._tools.keyword_search}[name]
            return method(ctx, query, scope, limit)
        if name == _LIST_TOOL:
            return self._tools.list_documents(ctx, scope)
        return self._tools.read_document(ctx, source_id, scope, offset, limit)

    def _record(
        self, ctx: RequestContext, tool: str, scope: List[str], start_ns: int,
        error: Optional[Exception] = None, **metadata,
    ) -> None:
        self.tracing.record(SpanEvent(
            trace_id=ctx.trace_id, span="rag", start_ns=start_ns, end_ns=time.perf_counter_ns(),
            status="error" if error else "ok", error=str(error) if error else "",
            meta={"tool": tool, "knowledge_base_ids": scope, "request_id": ctx.request_id,
                  "user_id": ctx.user_id, "session_id": ctx.session_id, **metadata},
        ))
