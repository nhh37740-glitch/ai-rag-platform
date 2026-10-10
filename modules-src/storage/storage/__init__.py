# cython: annotation_typing=False
from __future__ import annotations

import json
import os
import sqlite3
import threading
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from core_specifications import MemoryEntry, MemoryStorePort, RequestContext, VectorStore

__version__ = "0.3.0"


class _SqliteStore:
    def __init__(self, db_path: str) -> None:
        if db_path != ":memory:":
            os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self._lock = threading.RLock()
        self._closed = False
        self._conn = sqlite3.connect(db_path, check_same_thread=False)

    def _require_open(self) -> None:
        if self._closed:
            raise RuntimeError("store is closed")

    def _create_schema(self, statements: List[str]) -> None:
        try:
            with self._conn:
                for statement in statements:
                    self._conn.execute(statement)
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._conn.close()
                self._closed = True


def _vector(value: Any) -> np.ndarray:
    try:
        vector = np.asarray(value, dtype=np.float64)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("embedding must contain finite numbers") from exc
    if vector.ndim != 1 or vector.size == 0 or not np.isfinite(vector).all():
        raise ValueError("embedding must be a non-empty one-dimensional finite vector")
    return vector


def _top_k(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("top_k must be an integer")
    if value < 1:
        raise ValueError("top_k must be positive")


class SqliteVectorStore(_SqliteStore):
    """Persistent JSON vectors, ranked by dot product; no RAG dependency."""

    def __init__(self, db_path: str) -> None:
        super().__init__(db_path)
        self._create_schema([
            "CREATE TABLE IF NOT EXISTS vectors (source_id TEXT, text TEXT, embedding TEXT)",
            "CREATE INDEX IF NOT EXISTS vectors_source ON vectors(source_id)",
        ])

    def add(self, source_id: str, chunks: List[str], embeddings: Any) -> None:
        with self._lock:
            self._require_open()
            if not isinstance(source_id, str) or not source_id.strip():
                raise ValueError("source_id must be non-empty")
            texts = list(chunks)
            raw_vectors = list(embeddings)
            if len(texts) != len(raw_vectors):
                raise ValueError("chunk and embedding counts must match")
            if any(not isinstance(text, str) for text in texts):
                raise TypeError("chunks must contain strings")
            vectors = [_vector(value) for value in raw_vectors]
            if len({vector.size for vector in vectors}) > 1:
                raise ValueError("embedding dimensions must match")
            existing = self._conn.execute("SELECT embedding FROM vectors").fetchall()
            dimensions = {_vector(json.loads(row[0])).size for row in existing}
            if vectors and any(size != vectors[0].size for size in dimensions):
                raise ValueError("embedding dimension differs from the stored collection")
            rows = [
                (source_id, text, json.dumps(vector.tolist(), allow_nan=False))
                for text, vector in zip(texts, vectors)
            ]
            with self._conn:
                self._conn.execute("DELETE FROM vectors WHERE source_id = ?", (source_id,))
                self._conn.executemany(
                    "INSERT INTO vectors (source_id, text, embedding) VALUES (?, ?, ?)", rows
                )

    def search(
        self, embedding: Any, top_k: int = 5, scopes: Optional[List[str]] = None
    ) -> List[tuple[str, str, float]]:
        with self._lock:
            self._require_open()
            _top_k(top_k)
            query = _vector(embedding)
            allowed = set(scopes) if scopes is not None else None
            if allowed == set():
                return []
            stored = self._conn.execute(
                "SELECT source_id, text, embedding FROM vectors ORDER BY rowid"
            ).fetchall()
            hits = []
            for source_id, text, raw_embedding in stored:
                if allowed is not None and source_id.partition("/")[0] not in allowed:
                    continue
                vector = _vector(json.loads(raw_embedding))
                if vector.size != query.size:
                    raise ValueError("query embedding dimension differs from stored vector")
                score = float(np.dot(vector, query))
                if not np.isfinite(score):
                    raise ValueError("vector score is not finite")
                hits.append((source_id, text, score))
            return sorted(hits, key=lambda hit: -hit[2])[:top_k]

    def list_documents(self, scopes: Optional[List[str]] = None) -> List[tuple[str, int]]:
        with self._lock:
            self._require_open()
            allowed = set(scopes) if scopes is not None else None
            rows = self._conn.execute(
                "SELECT source_id, COUNT(*) FROM vectors GROUP BY source_id ORDER BY source_id"
            ).fetchall()
            return [
                (source_id, count) for source_id, count in rows
                if allowed is None or source_id.partition("/")[0] in allowed
            ]

    def document_chunks(self, source_id: str) -> List[str]:
        with self._lock:
            self._require_open()
            rows = self._conn.execute(
                "SELECT text FROM vectors WHERE source_id = ? ORDER BY rowid", (source_id,)
            ).fetchall()
            return [text for (text,) in rows]


class StateStore(_SqliteStore):
    """User-scoped persistent JSON values; never exposes a raw connection."""

    def __init__(self, db_path: str) -> None:
        super().__init__(db_path)
        self._create_schema([
            "CREATE TABLE IF NOT EXISTS state (user_id TEXT NOT NULL, key TEXT NOT NULL, "
            "payload TEXT NOT NULL, PRIMARY KEY (user_id, key))",
        ])

    def get(self, ctx: RequestContext, key: str) -> Any:
        with self._lock:
            self._require_open()
            row = self._conn.execute(
                "SELECT payload FROM state WHERE user_id = ? AND key = ?", (ctx.user_id, key)
            ).fetchone()
            return json.loads(row[0]) if row else None

    def set(self, ctx: RequestContext, key: str, value: Any) -> None:
        with self._lock:
            self._require_open()
            payload = json.dumps(value, ensure_ascii=False, allow_nan=False)
            with self._conn:
                self._conn.execute(
                    "INSERT OR REPLACE INTO state (user_id, key, payload) VALUES (?, ?, ?)",
                    (ctx.user_id, key, payload),
                )

    def delete(self, ctx: RequestContext, key: str) -> None:
        with self._lock:
            self._require_open()
            with self._conn:
                self._conn.execute("DELETE FROM state WHERE user_id = ? AND key = ?", (ctx.user_id, key))

    def increment_if_below(self, ctx: RequestContext, key: str, limit: int) -> Optional[int]:
        """Atomically reserve one unit across threads and SQLite connections."""
        if not isinstance(key, str) or not key.strip():
            raise ValueError("counter key must be non-empty")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError("counter limit must be a positive integer")
        with self._lock:
            self._require_open()
            with self._conn:
                self._conn.execute("BEGIN IMMEDIATE")
                row = self._conn.execute(
                    "SELECT payload FROM state WHERE user_id = ? AND key = ?", (ctx.user_id, key)
                ).fetchone()
                used = json.loads(row[0]) if row else 0
                if type(used) is not int or used < 0:
                    raise ValueError("counter must be a non-negative integer")
                if used >= limit:
                    return None
                used += 1
                self._conn.execute(
                    "INSERT OR REPLACE INTO state (user_id, key, payload) VALUES (?, ?, ?)",
                    (ctx.user_id, key, json.dumps(used)),
                )
                return used


class Storage(_SqliteStore):
    """Legacy composition API; injected memory/vector stores remain caller-owned."""

    def __init__(self, memory_store: MemoryStorePort, vector_store: VectorStore, db_path: str) -> None:
        super().__init__(db_path)
        self.mem = memory_store
        self.vs = vector_store
        self._create_schema([
            "CREATE TABLE IF NOT EXISTS eval (run_id TEXT PRIMARY KEY, payload TEXT, created TEXT)",
        ])

    def memory_write(self, ctx: RequestContext, namespace: str, key: str, content: str, importance: float = 0.0) -> MemoryEntry:
        with self._lock:
            self._require_open()
            return self.mem.write(ctx, namespace, key, content, importance)

    def memory_get(self, ctx: RequestContext, namespace: str, key: str) -> Optional[MemoryEntry]:
        with self._lock:
            self._require_open()
            return self.mem.get(ctx, namespace, key)

    def memory_search(self, ctx: RequestContext, namespace: str, query: str, top_k: int = 5) -> List[MemoryEntry]:
        with self._lock:
            self._require_open()
            return self.mem.search(ctx, namespace, query, top_k)

    def memory_forget(self, ctx: RequestContext, namespace: str, key: str) -> None:
        with self._lock:
            self._require_open()
            self.mem.forget(ctx, namespace, key)

    def add_documents(self, source_id: str, chunks: List[str], embeddings: Any) -> None:
        with self._lock:
            self._require_open()
            self.vs.add(source_id, chunks, embeddings)

    def search_documents(self, query_embedding: Any, top_k: int = 5) -> List[Tuple[str, float]]:
        with self._lock:
            self._require_open()
            return [(sid, score) for sid, _text, score in self.vs.search(query_embedding, top_k)]

    def save_eval(self, run_id: str, payload: Dict[str, Any]) -> None:
        with self._lock:
            self._require_open()
            with self._conn:
                self._conn.execute(
                    "INSERT OR REPLACE INTO eval (run_id, payload, created) VALUES (?,?,datetime('now'))",
                    (run_id, json.dumps(payload, ensure_ascii=False, allow_nan=False)),
                )

    def load_eval(self, run_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            self._require_open()
            row = self._conn.execute("SELECT payload FROM eval WHERE run_id=?", (run_id,)).fetchone()
            return json.loads(row[0]) if row else None


def make_storage(db_path: str, memory_store: MemoryStorePort, vector_store: VectorStore) -> Storage:
    return Storage(memory_store, vector_store, db_path)


__all__ = ["SqliteVectorStore", "StateStore", "Storage", "make_storage"]
