# cython: annotation_typing=False
from __future__ import annotations

import os
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from core_specifications import MemoryEntry, RequestContext

__version__ = "0.2.0"


class MemoryStore:
    """SQLite memory keyed by namespace/user, compatible with existing tables."""

    def __init__(self, db_path: str) -> None:
        if db_path != ":memory:":
            os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self._lock = threading.RLock()
        self._closed = False
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        try:
            with self._conn:
                self._conn.execute(
                    "CREATE TABLE IF NOT EXISTS memory (id TEXT PRIMARY KEY, namespace TEXT, key TEXT, content TEXT, created TEXT, importance REAL, user_id TEXT)"
                )
        except BaseException:
            self._conn.close()
            self._closed = True
            raise

    def _ctx(self, ctx: RequestContext) -> RequestContext:
        if self._closed:
            raise RuntimeError("memory store is closed")
        if ctx is None:
            raise ValueError("ctx required")
        return ctx

    def write(self, ctx: RequestContext, namespace: str, key: str, content: str, importance: float = 0.0) -> MemoryEntry:
        with self._lock:
            c = self._ctx(ctx)
            entry = MemoryEntry(
                id=uuid.uuid4().hex, namespace=namespace, key=key, content=content,
                created=datetime.now(timezone.utc).isoformat(), importance=importance,
            )
            with self._conn:
                self._conn.execute(
                    "DELETE FROM memory WHERE namespace=? AND key=? AND user_id=?", (namespace, key, c.user_id)
                )
                self._conn.execute(
                    "INSERT INTO memory (id, namespace, key, content, created, importance, user_id) VALUES (?,?,?,?,?,?,?)",
                    (entry.id, entry.namespace, entry.key, entry.content, entry.created, entry.importance, c.user_id),
                )
            return entry

    def get(self, ctx: RequestContext, namespace: str, key: str) -> Optional[MemoryEntry]:
        with self._lock:
            c = self._ctx(ctx)
            row = self._conn.execute(
                "SELECT id, namespace, key, content, created, importance FROM memory WHERE namespace=? AND key=? AND user_id=? ORDER BY rowid DESC LIMIT 1",
                (namespace, key, c.user_id),
            ).fetchone()
            return MemoryEntry(*row) if row else None

    def search(self, ctx: RequestContext, namespace: str, query: str, top_k: int = 5) -> List[MemoryEntry]:
        with self._lock:
            c = self._ctx(ctx)
            if isinstance(top_k, bool) or not isinstance(top_k, int):
                raise TypeError("top_k must be an integer")
            if top_k < 1:
                raise ValueError("top_k must be positive")
            rows = self._conn.execute(
                "SELECT id, namespace, key, content, created, importance FROM memory WHERE namespace=? AND user_id=?",
                (namespace, c.user_id),
            ).fetchall()
            terms = [term for term in query.replace("？", " ").replace("?", " ").split() if term]
            scored = []
            for row in rows:
                entry = MemoryEntry(*row)
                score = sum(1 for term in terms if term in entry.content) + entry.importance
                scored.append((score, entry))
            scored.sort(key=lambda item: -item[0])
            return [entry for _, entry in scored[:top_k]]

    def forget(self, ctx: RequestContext, namespace: str, key: str) -> None:
        with self._lock:
            c = self._ctx(ctx)
            with self._conn:
                self._conn.execute("DELETE FROM memory WHERE namespace=? AND key=? AND user_id=?", (namespace, key, c.user_id))

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._conn.close()
                self._closed = True


def make_memory(db_path: str) -> MemoryStore:
    return MemoryStore(db_path)


__all__ = ["MemoryStore", "make_memory"]
