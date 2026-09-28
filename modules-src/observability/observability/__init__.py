from __future__ import annotations

import threading
import time
from collections import deque
from typing import Dict, List

from core_contracts import RequestContext, SpanEvent

__version__ = "0.1.0"


class TraceStore:
    """按 trace_id 归集跨模块的 span 事件，供 /api/trace/{id} 查看全链路。"""

    def __init__(self, maxlen: int = 2000) -> None:
        self._buffers: Dict[str, deque] = {}
        self._maxlen = maxlen
        self._lock = threading.Lock()

    def record(self, span: SpanEvent) -> None:
        with self._lock:
            d = self._buffers.setdefault(span.trace_id, deque(maxlen=self._maxlen))
            d.append(span)

    def get(self, trace_id: str) -> List[SpanEvent]:
        with self._lock:
            return list(self._buffers.get(trace_id, []))


class Span:
    """同步上下文管理器，记录某段逻辑的耗时与成败。"""

    def __init__(self, ctx: RequestContext, name: str, store: TraceStore | None = None) -> None:
        self.ctx = ctx
        self.name = name
        self.store = store
        self._start = 0

    def __enter__(self) -> "Span":
        self._start = time.perf_counter_ns()
        return self

    def __exit__(self, et, ev, tb) -> bool:
        end = time.perf_counter_ns()
        if self.store is not None:
            status = "error" if ev else "ok"
            self.store.record(
                SpanEvent(
                    self.ctx.trace_id,
                    self.name,
                    self._start,
                    end,
                    status,
                    "" if not ev else str(ev),
                    {"request_id": self.ctx.request_id, "user_id": self.ctx.user_id},
                )
            )
        return False


class ASpan:
    """异步上下文管理器，见 Span。"""

    def __init__(self, ctx: RequestContext, name: str, store: TraceStore | None = None) -> None:
        self._s = Span(ctx, name, store)

    async def __aenter__(self) -> "ASpan":
        self._s.__enter__()
        return self

    async def __aexit__(self, et, ev, tb) -> bool:
        return self._s.__exit__(et, ev, tb)


def make_trace_store() -> TraceStore:
    return TraceStore()


__all__ = ["TraceStore", "Span", "ASpan", "make_trace_store"]
