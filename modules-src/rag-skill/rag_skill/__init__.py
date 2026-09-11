from __future__ import annotations

import json
import time
from typing import Any, Iterable, List, Optional, Protocol

from core_contracts import Citation, RequestContext, SpanEvent, ToolDef
from rag_core import retrieve

__version__ = "0.1.0"

MIN_TOP_K = 1
MAX_TOP_K = 20
TEXT_PREVIEW_LENGTH = 160


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


class RagSkill:
    """Expose scoped knowledge-base retrieval as an Agent tool."""

    def __init__(self, store: Any, tracing: _TraceStore, top_k: int = 5) -> None:
        self.store = store
        self.tracing = tracing
        self.top_k = _validate_top_k(top_k)

    def tool_definition(self) -> ToolDef:
        return ToolDef(
            name="search_knowledge_base",
            description=(
                "在当前对话已选择的知识库中检索相关资料。"
                "当现有结果不足时，可以改写 query 再次调用。"
            ),
            parameters={
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
            },
        )

    def execute(
        self,
        ctx: RequestContext,
        query: str,
        knowledge_base_ids: List[str],
        top_k: Optional[int] = None,
    ) -> str:
        start_ns = time.perf_counter_ns()
        scope_for_trace: List[str] = []
        normalized_query = query.strip() if isinstance(query, str) else str(query)
        meta: dict[str, Any] = {
            "query": normalized_query,
            "knowledge_base_ids": scope_for_trace,
            "hit_count": 0,
            "hits": [],
        }
        succeeded = False

        try:
            if not isinstance(query, str):
                raise TypeError("query 必须是字符串")
            normalized_query = query.strip()
            if not normalized_query:
                raise ValueError("query 不能为空")

            scope_for_trace = _normalize_knowledge_base_ids(knowledge_base_ids)
            meta["query"] = normalized_query
            meta["knowledge_base_ids"] = scope_for_trace
            limit = self.top_k if top_k is None else _validate_top_k(top_k)

            result = retrieve(
                ctx,
                normalized_query,
                self.store,
                scope=scope_for_trace,
                top_k=limit,
            )
            citations = list(result.citations)
            meta["hit_count"] = len(citations)
            meta["hits"] = _hit_meta(citations)

            payload = json.dumps(
                {
                    "query": result.query,
                    "hit_count": len(citations),
                    "citations": [_citation_payload(item) for item in citations],
                },
                ensure_ascii=False,
            )
            succeeded = True
            return payload
        except Exception as exc:
            self.tracing.record(
                SpanEvent(
                    trace_id=ctx.trace_id,
                    span="rag",
                    start_ns=start_ns,
                    end_ns=time.perf_counter_ns(),
                    status="error",
                    error=str(exc),
                    meta=meta,
                )
            )
            raise
        finally:
            if succeeded:
                self.tracing.record(
                    SpanEvent(
                        trace_id=ctx.trace_id,
                        span="rag",
                        start_ns=start_ns,
                        end_ns=time.perf_counter_ns(),
                        status="ok",
                        error="",
                        meta=meta,
                    )
                )


__all__ = ["MAX_TOP_K", "MIN_TOP_K", "RagSkill"]
