from __future__ import annotations

import json
import time
from typing import Any, Callable, Iterable, List, Optional, Protocol

from core_contracts import Citation, RequestContext, SpanEvent, ToolDef
from rag_core import DEFAULT_READ_CHUNKS
from rag_core import MAX_READ_CHUNKS
from rag_core import document_info as run_document_info
from rag_core import hybrid_search as run_hybrid_search
from rag_core import keyword_search as run_keyword_search
from rag_core import list_documents as run_list_documents
from rag_core import read_document as run_read_document
from rag_core import retrieve

__version__ = "0.2.0"

MIN_TOP_K = 1
MAX_TOP_K = 20
TEXT_PREVIEW_LENGTH = 160

SEARCH_TOOL = "search_knowledge_base"
HYBRID_TOOL = "hybrid_search_knowledge_base"
KEYWORD_TOOL = "keyword_search_knowledge_base"
LIST_TOOL = "list_knowledge_documents"
READ_TOOL = "read_knowledge_document"


class _TraceStore(Protocol):
    def record(self, span: SpanEvent) -> None: ...


def _validate_top_k(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("top_k 必须是整数")
    if not MIN_TOP_K <= value <= MAX_TOP_K:
        raise ValueError(f"top_k 必须在 {MIN_TOP_K} 到 {MAX_TOP_K} 之间")
    return value


def _normalize_knowledge_base_ids(values: Iterable[str]) -> List[str]:
    if isinstance(values, (str, bytes)):
        raise TypeError("knowledge_base_ids 必须是字符串列表")

    normalized: List[str] = []
    seen = set()
    for value in values:
        if not isinstance(value, str):
            raise TypeError("knowledge_base_ids 中的每一项都必须是字符串")
        knowledge_base_id = value.strip()
        if not knowledge_base_id:
            raise ValueError("knowledge_base_ids 不能包含空值")
        if knowledge_base_id not in seen:
            seen.add(knowledge_base_id)
            normalized.append(knowledge_base_id)
    return normalized


def _require_query(query: str) -> str:
    if not isinstance(query, str):
        raise TypeError("query 必须是字符串")
    normalized = query.strip()
    if not normalized:
        raise ValueError("query 不能为空")
    return normalized


def _validate_max_chunks(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("max_chunks 必须是整数")
    if not 1 <= value <= MAX_READ_CHUNKS:
        raise ValueError(f"max_chunks 必须在 1 到 {MAX_READ_CHUNKS} 之间")
    return value


def _validate_offset(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("offset 必须是整数")
    if value < 0:
        raise ValueError("offset 不能为负数")
    return value


def _preview(text: str) -> str:
    compact = " ".join(text.split())
    if len(compact) <= TEXT_PREVIEW_LENGTH:
        return compact
    return compact[: TEXT_PREVIEW_LENGTH - 1] + "…"


def _hit_meta(citations: List[Citation]) -> List[dict[str, Any]]:
    return [
        {
            "rank": rank,
            "source_id": citation.source_id,
            "title": citation.title,
            "score": float(citation.score),
            "text_preview": _preview(citation.text),
        }
        for rank, citation in enumerate(citations, start=1)
    ]


def _citation_payload(citation: Citation) -> dict[str, Any]:
    return {
        "source_id": citation.source_id,
        "title": citation.title,
        "text": citation.text,
        "score": float(citation.score),
        "metadata": citation.metadata,
    }


def _search_parameters() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "minLength": 1,
                "description": "用于知识库检索的明确查询词或问题",
            },
            "top_k": {
                "type": "integer",
                "minimum": MIN_TOP_K,
                "maximum": MAX_TOP_K,
                "description": "返回的最大命中数量",
            },
        },
        "required": ["query"],
        "additionalProperties": False,
    }


def _list_parameters() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": False,
    }


def _read_parameters() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "source_id": {
                "type": "string",
                "minLength": 1,
                "description": "目标文档的 source_id，可从检索结果或文档清单中获得",
            },
            "offset": {
                "type": "integer",
                "minimum": 0,
                "description": "从第几块开始读，用于续读被截断的文档",
            },
            "max_chunks": {
                "type": "integer",
                "minimum": 1,
                "maximum": MAX_READ_CHUNKS,
                "description": f"本次最多读取多少块，默认 {DEFAULT_READ_CHUNKS}",
            },
        },
        "required": ["source_id"],
        "additionalProperties": False,
    }


class RagTools:
    """把知识库检索能力包装成 LLM 可直接调用的工具集合。

    五个工具共享同一条硬约束：检索范围只能由当前请求注入，模型无法通过工具参数
    查看或扩大知识库范围；``read_knowledge_document`` 还会拒绝范围外的 ``source_id``。
    """

    def __init__(self, store: Any, tracing: _TraceStore, top_k: int = 5) -> None:
        self.store = store
        self.tracing = tracing
        self.top_k = _validate_top_k(top_k)

    # ------------------------------------------------------------------ 工具定义

    def tool_definitions(self) -> List[ToolDef]:
        return [
            ToolDef(
                name=SEARCH_TOOL,
                description=(
                    "在当前对话已选择的知识库中做向量语义检索。"
                    "结果不理想时可改写 query 后再次调用，或改用其他检索工具。"
                ),
                parameters=_search_parameters(),
            ),
            ToolDef(
                name=HYBRID_TOOL,
                description=(
                    "同时使用向量与关键词的融合检索。"
                    "语义检索结果不相关或缺少直接证据时优先用这个工具重试。"
                ),
                parameters=_search_parameters(),
            ),
            ToolDef(
                name=KEYWORD_TOOL,
                description=(
                    "按关键词或专有名词在当前所选知识库中做词面精确匹配。"
                    "当语义检索没有命中、而你知道原文可能出现的术语、人名或标题时使用。"
                ),
                parameters=_search_parameters(),
            ),
            ToolDef(
                name=LIST_TOOL,
                description=(
                    "列出当前所选知识库里的全部文档标题与 source_id。"
                    "多轮检索都无结果时用它确认知识库实际收录了哪些资料。"
                ),
                parameters=_list_parameters(),
            ),
            ToolDef(
                name=READ_TOOL,
                description=(
                    "按 source_id 分页读取某篇文档的原文，默认只返回前 "
                    f"{DEFAULT_READ_CHUNKS} 块，上限 {MAX_READ_CHUNKS} 块。"
                    "不要假设一次能读完整篇文档：返回的 truncated 为 true 时，"
                    "必须用 next_offset 作为新的 offset 继续读，直到 truncated 为 false。"
                    "先用检索或文档清单确定 source_id 后再调用。"
                ),
                parameters=_read_parameters(),
            ),
        ]

    # ------------------------------------------------------------------ 公开方法

    def search(
        self,
        ctx: RequestContext,
        query: str,
        knowledge_base_ids: List[str],
        top_k: Optional[int] = None,
    ) -> str:
        return self._run_search_tool(
            SEARCH_TOOL,
            ctx,
            query,
            knowledge_base_ids,
            top_k,
            lambda normalized, scope, limit: retrieve(
                ctx, normalized, self.store, scope=scope, top_k=limit
            ),
        )

    def hybrid_search(
        self,
        ctx: RequestContext,
        query: str,
        knowledge_base_ids: List[str],
        top_k: Optional[int] = None,
    ) -> str:
        return self._run_search_tool(
            HYBRID_TOOL,
            ctx,
            query,
            knowledge_base_ids,
            top_k,
            lambda normalized, scope, limit: run_hybrid_search(
                ctx, normalized, self.store, scope=scope, top_k=limit
            ),
        )

    def keyword_search(
        self,
        ctx: RequestContext,
        query: str,
        knowledge_base_ids: List[str],
        top_k: Optional[int] = None,
    ) -> str:
        return self._run_search_tool(
            KEYWORD_TOOL,
            ctx,
            query,
            knowledge_base_ids,
            top_k,
            lambda normalized, scope, limit: run_keyword_search(
                ctx, normalized, self.store, scope=scope, top_k=limit
            ),
        )

    def list_documents(self, ctx: RequestContext, knowledge_base_ids: List[str]) -> str:
        start_ns = time.perf_counter_ns()
        scope_for_trace: List[str] = []
        meta: dict[str, Any] = {
            "tool": LIST_TOOL,
            "query": "",
            "knowledge_base_ids": scope_for_trace,
            "hit_count": 0,
            "hits": [],
        }
        succeeded = False
        try:
            scope_for_trace = _normalize_knowledge_base_ids(knowledge_base_ids)
            meta["knowledge_base_ids"] = scope_for_trace
            documents = run_list_documents(ctx, self.store, scope=scope_for_trace)
            meta["hit_count"] = len(documents)
            payload = json.dumps(
                {
                    "tool": LIST_TOOL,
                    "document_count": len(documents),
                    "documents": documents,
                },
                ensure_ascii=False,
            )
            succeeded = True
            return payload
        except Exception as exc:
            self._record(ctx, start_ns, "error", str(exc), meta)
            raise
        finally:
            if succeeded:
                self._record(ctx, start_ns, "ok", "", meta)

    def read_document(
        self,
        ctx: RequestContext,
        source_id: str,
        knowledge_base_ids: List[str],
        offset: int = 0,
        max_chunks: Optional[int] = None,
    ) -> str:
        start_ns = time.perf_counter_ns()
        normalized_source = source_id.strip() if isinstance(source_id, str) else str(source_id)
        scope_for_trace: List[str] = []
        meta: dict[str, Any] = {
            "tool": READ_TOOL,
            "query": normalized_source,
            "knowledge_base_ids": scope_for_trace,
            "hit_count": 0,
            "hits": [],
            "offset": offset,
            "max_chunks": max_chunks,
            "truncated": False,
        }
        succeeded = False
        try:
            if not isinstance(source_id, str):
                raise TypeError("source_id 必须是字符串")
            normalized_source = source_id.strip()
            if not normalized_source:
                raise ValueError("source_id 不能为空")
            normalized_offset = _validate_offset(offset)
            limit = DEFAULT_READ_CHUNKS if max_chunks is None else _validate_max_chunks(max_chunks)

            scope_for_trace = _normalize_knowledge_base_ids(knowledge_base_ids)
            meta["knowledge_base_ids"] = scope_for_trace
            if normalized_source.partition("/")[0] not in scope_for_trace:
                raise ValueError("source_id 不在当前知识库范围内")

            info = run_document_info(ctx, self.store, normalized_source)
            total_chunks = int(info["chunk_count"])
            result = run_read_document(
                ctx,
                self.store,
                normalized_source,
                max_chunks=limit,
                offset=normalized_offset,
            )
            citations = list(result.citations)
            returned_chunks = len(citations)
            truncated = normalized_offset + returned_chunks < total_chunks
            next_offset = normalized_offset + returned_chunks if truncated else None

            meta["query"] = normalized_source
            meta["hit_count"] = returned_chunks
            meta["hits"] = _hit_meta(citations)
            meta["offset"] = normalized_offset
            meta["max_chunks"] = limit
            meta["truncated"] = truncated
            payload = json.dumps(
                {
                    "tool": READ_TOOL,
                    "source_id": normalized_source,
                    "query": result.query,
                    "offset": normalized_offset,
                    "max_chunks": limit,
                    "returned_chunks": returned_chunks,
                    "total_chunks": total_chunks,
                    "truncated": truncated,
                    "next_offset": next_offset,
                    "hit_count": returned_chunks,
                    "citations": [_citation_payload(item) for item in citations],
                },
                ensure_ascii=False,
            )
            succeeded = True
            return payload
        except Exception as exc:
            self._record(ctx, start_ns, "error", str(exc), meta)
            raise
        finally:
            if succeeded:
                self._record(ctx, start_ns, "ok", "", meta)

    # ------------------------------------------------------------------ 内部实现

    def _run_search_tool(
        self,
        tool_name: str,
        ctx: RequestContext,
        query: str,
        knowledge_base_ids: List[str],
        top_k: Optional[int],
        runner: Callable[[str, List[str], int], Any],
    ) -> str:
        start_ns = time.perf_counter_ns()
        normalized_query = query.strip() if isinstance(query, str) else str(query)
        scope_for_trace: List[str] = []
        meta: dict[str, Any] = {
            "tool": tool_name,
            "query": normalized_query,
            "knowledge_base_ids": scope_for_trace,
            "hit_count": 0,
            "hits": [],
        }
        succeeded = False
        try:
            normalized_query = _require_query(query)
            scope_for_trace = _normalize_knowledge_base_ids(knowledge_base_ids)
            limit = self.top_k if top_k is None else _validate_top_k(top_k)
            meta["query"] = normalized_query
            meta["knowledge_base_ids"] = scope_for_trace

            result = runner(normalized_query, scope_for_trace, limit)
            citations = list(result.citations)
            meta["hit_count"] = len(citations)
            meta["hits"] = _hit_meta(citations)
            payload = json.dumps(
                {
                    "tool": tool_name,
                    "query": result.query,
                    "hit_count": len(citations),
                    "citations": [_citation_payload(item) for item in citations],
                },
                ensure_ascii=False,
            )
            succeeded = True
            return payload
        except Exception as exc:
            self._record(ctx, start_ns, "error", str(exc), meta)
            raise
        finally:
            if succeeded:
                self._record(ctx, start_ns, "ok", "", meta)

    def _record(
        self,
        ctx: RequestContext,
        start_ns: int,
        status: str,
        error: str,
        meta: dict[str, Any],
    ) -> None:
        self.tracing.record(
            SpanEvent(
                trace_id=ctx.trace_id,
                span="rag",
                start_ns=start_ns,
                end_ns=time.perf_counter_ns(),
                status=status,
                error=error,
                meta=meta,
            )
        )


__all__ = ["MAX_TOP_K", "MIN_TOP_K", "RagTools"]
