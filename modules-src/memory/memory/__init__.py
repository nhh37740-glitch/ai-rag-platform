from __future__ import annotations

import os
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from core_contracts import MemoryEntry, RequestContext

__version__ = "0.1.0"


class MemoryStore:
    """session/user 双命名空间的 SQLite 记忆库。仅本模块可写库。"""

    def __init__(self, db_path: str) -> None:
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS memory (id TEXT PRIMARY KEY, namespace TEXT, key TEXT, content TEXT, created TEXT, importance REAL, user_id TEXT)"
        )
        self._conn.commit()

    def _ctx(self, ctx: RequestContext):
        if ctx is None:
            raise ValueError("ctx required")
        return ctx

    def write(self, ctx, namespace: str, key: str, content: str, importance: float = 0.0) -> MemoryEntry:
        c = self._ctx(ctx)
        e = MemoryEntry(
            id=uuid.uuid4().hex,
            namespace=namespace,
            key=key,
            content=content,
            created=datetime.now(timezone.utc).isoformat(),
            importance=importance,
        )
        self._conn.execute(
            "INSERT OR REPLACE INTO memory (id, namespace, key, content, created, importance, user_id) VALUES (?,?,?,?,?,?,?)",
            (e.id, e.namespace, e.key, e.content, e.created, e.importance, c.user_id),
        )
        self._conn.commit()
        return e

    def get(self, ctx, namespace: str, key: str) -> Optional[MemoryEntry]:
        c = self._ctx(ctx)
        row = self._conn.execute(
            "SELECT id, namespace, key, content, created, importance FROM memory WHERE namespace=? AND key=? AND user_id=?",
            (namespace, key, c.user_id),
        ).fetchone()
        return MemoryEntry(*row) if row else None

    def search(self, ctx, namespace: str, query: str, top_k: int = 5) -> List[MemoryEntry]:
        c = self._ctx(ctx)
        rows = self._conn.execute(
            "SELECT id, namespace, key, content, created, importance FROM memory WHERE namespace=? AND user_id=?",
            (namespace, c.user_id),
        ).fetchall()
        terms = [t for t in query.replace("？", " ").replace("?", " ").split() if t]
        scored = []
        for r in rows:
            e = MemoryEntry(*r)
            score = sum(1 for t in terms if t in e.content) + e.importance
            scored.append((score, e))
        scored.sort(key=lambda x: -x[0])
        return [e for _, e in scored[:top_k]]

    def forget(self, ctx, namespace: str, key: str) -> None:
        c = self._ctx(ctx)
        self._conn.execute("DELETE FROM memory WHERE namespace=? AND key=? AND user_id=?", (namespace, key, c.user_id))
        self._conn.commit()


def make_memory(db_path: str) -> MemoryStore:
    return MemoryStore(db_path)


__all__ = ["MemoryStore", "make_memory"]
