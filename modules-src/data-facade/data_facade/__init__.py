# cython: annotation_typing=False
from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional

from core_specifications import MemoryStorePort, RequestContext, StateStorePort, VectorStore
from memory import MemoryStore
from storage import SqliteVectorStore, StateStore

__version__ = "0.1.0"


class DataService:
    """Owns the three persistent stores for the database domain."""

    def __init__(
        self, state_dir: str, memory_db_path: str | None = None,
        vector_db_path: str | None = None,
    ) -> None:
        self._state_dir = Path(state_dir)
        self._memory_path = memory_db_path if memory_db_path is not None else str(self._state_dir / "memory.sqlite")
        self._vector_path = vector_db_path if vector_db_path is not None else str(self._state_dir / "vectors.sqlite")
        self._memory: Optional[MemoryStore] = None
        self._vectors: Optional[SqliteVectorStore] = None
        self._state: Optional[StateStore] = None
        self._lock = threading.RLock()
        self._closed = False

    def _require_open(self) -> None:
        if self._closed:
            raise RuntimeError("data service is closed")

    def initialize(self, ctx: RequestContext) -> None:
        with self._lock:
            self._require_open()
            if self._memory is not None:
                return
            self._state_dir.mkdir(parents=True, exist_ok=True)
            owned = []
            try:
                memory = MemoryStore(self._memory_path)
                owned.append(memory)
                vectors = SqliteVectorStore(self._vector_path)
                owned.append(vectors)
                state = StateStore(str(self._state_dir / "state.sqlite"))
                owned.append(state)
            except Exception:
                for store in reversed(owned):
                    store.close()
                raise
            self._memory, self._vectors, self._state = memory, vectors, state

    def memory_store(self, ctx: RequestContext) -> MemoryStorePort:
        with self._lock:
            self.initialize(ctx)
            return self._memory

    def vector_store(self, ctx: RequestContext) -> VectorStore:
        with self._lock:
            self.initialize(ctx)
            return self._vectors

    def state_db(self, ctx: RequestContext) -> StateStorePort:
        with self._lock:
            self.initialize(ctx)
            return self._state

    def close(self, ctx: RequestContext) -> None:
        with self._lock:
            if self._closed:
                return
            for store in (self._state, self._vectors, self._memory):
                if store is not None:
                    store.close()
            self._closed = True


__all__ = ["DataService"]
