from __future__ import annotations

import json
import os
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

from core_contracts import MemoryEntry, RequestContext, RetrievalResult
from memory import MemoryStore
from rag_core import InMemoryVectorStore

__version__ = "0.1.0"


class Storage:
    """统一持久层：记忆 + 文档向量 + 评测结果，接口与 PostgreSQL+pgvector 同构，可平滑切换后端。"""

    def __init__(self, memory_store: MemoryStore, vector_store: InMemoryVectorStore, db_path: str) -> None:
        self.mem = memory_store
        self.vs = vector_store
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("CREATE TABLE IF NOT EXISTS eval (run_id TEXT PRIMARY KEY, payload TEXT, created TEXT)")
        self._conn.commit()

    # ---- memory ----
    def memory_write(self, ctx, namespace: str, key: str, content: str, importance: float = 0.0) -> MemoryEntry:
        return self.mem.write(ctx, namespace, key, content, importance)

    def memory_get(self, ctx, namespace: str, key: str) -> Optional[MemoryEntry]:
        return self.mem.get(ctx, namespace, key)

    def memory_search(self, ctx, namespace: str, query: str, top_k: int = 5) -> List[MemoryEntry]:
        return self.mem.search(ctx, namespace, query, top_k)

    def memory_forget(self, ctx, namespace: str, key: str) -> None:
        self.mem.forget(ctx, namespace, key)

    # ---- documents / vectors ----
    def add_documents(self, source_id: str, chunks: List[str], embeddings) -> None:
        self.vs.add(source_id, chunks, embeddings)

    def search_documents(self, query_embedding, top_k: int = 5) -> List[Tuple[str, float]]:
        return [(sid, score) for sid, _text, score in self.vs.search(query_embedding, top_k)]

    # ---- evaluation ----
    def save_eval(self, run_id: str, payload: Dict[str, Any]) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO eval (run_id, payload, created) VALUES (?,?,datetime('now'))",
            (run_id, json.dumps(payload, ensure_ascii=False)),
        )
        self._conn.commit()

    def load_eval(self, run_id: str) -> Optional[Dict[str, Any]]:
        row = self._conn.execute("SELECT payload FROM eval WHERE run_id=?", (run_id,)).fetchone()
        return json.loads(row[0]) if row else None


def make_storage(db_path: str, memory_store: MemoryStore, vector_store: InMemoryVectorStore) -> Storage:
    return Storage(memory_store, vector_store, db_path)


__all__ = ["Storage", "make_storage"]
