# cython: annotation_typing=False
from __future__ import annotations

import json
import os
import sqlite3
import threading
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from core_specifications import MemoryEntry, MemoryStorePort, RequestContext, VectorStore

__version__ = "0.4.0"


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


class NotebookStore(_SqliteStore):
    """Relational resource directory; authorization remains in auth-facade."""

    _columns = "notebook_id,owner_user_id,name,description,created_at,is_public,archived,acl_revision,legacy_migrated"

    def __init__(self, db_path: str) -> None:
        super().__init__(db_path)
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA busy_timeout=10000")
        self._create_schema([
            "CREATE TABLE IF NOT EXISTS schema_migrations(version TEXT PRIMARY KEY,applied_at TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS users(user_id TEXT PRIMARY KEY CHECK(length(user_id)>0),created_at TEXT NOT NULL,last_seen_at TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS roles(role_id TEXT PRIMARY KEY)",
            "CREATE TABLE IF NOT EXISTS permissions(permission_id TEXT PRIMARY KEY)",
            "CREATE TABLE IF NOT EXISTS role_permissions(role_id TEXT NOT NULL REFERENCES roles(role_id),permission_id TEXT NOT NULL REFERENCES permissions(permission_id),PRIMARY KEY(role_id,permission_id))",
            "CREATE TABLE IF NOT EXISTS notebooks(notebook_id TEXT PRIMARY KEY,owner_user_id TEXT NOT NULL REFERENCES users(user_id),name TEXT NOT NULL,description TEXT NOT NULL,created_at TEXT NOT NULL,is_public INTEGER NOT NULL CHECK(is_public IN(0,1)),archived INTEGER NOT NULL DEFAULT 0 CHECK(archived IN(0,1)),acl_revision INTEGER NOT NULL DEFAULT 0 CHECK(acl_revision>=0),legacy_migrated INTEGER NOT NULL DEFAULT 0 CHECK(legacy_migrated IN(0,1)))",
            "CREATE TABLE IF NOT EXISTS notebook_members(notebook_id TEXT NOT NULL REFERENCES notebooks(notebook_id),user_id TEXT NOT NULL REFERENCES users(user_id),role_id TEXT NOT NULL REFERENCES roles(role_id),PRIMARY KEY(notebook_id,user_id))",
            "CREATE INDEX IF NOT EXISTS notebook_members_user ON notebook_members(user_id,notebook_id)",
            "INSERT OR IGNORE INTO schema_migrations VALUES('1',datetime('now'))",
        ])

    @staticmethod
    def _identifier(value) -> str:
        if not isinstance(value, str) or not 0 < len(value) <= 128 or any(not (c.isalnum() or c in '@_.-') for c in value):
            raise ValueError("Invalid identifier")
        return value

    @staticmethod
    def _metadata(metadata: dict) -> tuple:
        if not isinstance(metadata, dict):
            raise ValueError("Invalid notebook metadata")
        notebook_id = NotebookStore._identifier(metadata.get('id'))
        owner_id = NotebookStore._identifier(metadata.get('owner_user_id'))
        name, description = metadata.get('name'), metadata.get('description', '')
        if not isinstance(name, str) or not 0 < len(name.strip()) <= 80 or not isinstance(description, str) or len(description) > 300:
            raise ValueError("Invalid notebook name or description")
        created = metadata.get('created_at')
        if not isinstance(created, str) or not created:
            raise ValueError("Invalid creation timestamp")
        public = metadata.get('is_public', False)
        if type(public) is not bool:
            raise ValueError("Invalid public flag")
        return notebook_id, owner_id, name.strip(), description.strip(), created, int(public)

    @staticmethod
    def _row(row) -> dict:
        value = dict(zip(('id','owner_user_id','name','description','created_at','is_public','archived','acl_revision','legacy_migrated'), row))
        for field in ('is_public','archived','legacy_migrated'):
            value[field] = bool(value[field])
        return value

    def configure_roles(self, ctx: RequestContext, roles: dict) -> None:
        if not isinstance(roles, dict) or not roles:
            raise ValueError("Invalid roles")
        for role, permissions in roles.items():
            self._identifier(role)
            if not isinstance(permissions, list) or not permissions:
                raise ValueError("Invalid permissions")
            for permission in permissions: self._identifier(permission)
        with self._lock:
            self._require_open()
            with self._conn:
                self._conn.execute('BEGIN IMMEDIATE')
                for role, permissions in roles.items():
                    inserted = self._conn.execute('INSERT OR IGNORE INTO roles VALUES(?)',(role,)).rowcount
                    if inserted:
                        for permission in permissions:
                            self._conn.execute('INSERT OR IGNORE INTO permissions VALUES(?)',(permission,))
                            self._conn.execute('INSERT INTO role_permissions VALUES(?,?)',(role,permission))

    def register_user(self, ctx: RequestContext, user_id: str) -> None:
        self._identifier(user_id)
        with self._lock:
            self._require_open()
            with self._conn:
                self._conn.execute("INSERT INTO users VALUES(?,datetime('now'),datetime('now')) ON CONFLICT(user_id) DO UPDATE SET last_seen_at=excluded.last_seen_at",(user_id,))

    def list_users(self, ctx: RequestContext) -> list[dict]:
        with self._lock:
            self._require_open()
            return [dict(zip(('user_id','created_at','last_seen_at'),row)) for row in self._conn.execute('SELECT * FROM users ORDER BY user_id').fetchall()]

    def create_notebook(self, ctx: RequestContext, metadata: dict) -> None:
        values = self._metadata(metadata)
        with self._lock:
            self._require_open()
            try:
                with self._conn:
                    self._conn.execute('INSERT INTO notebooks(notebook_id,owner_user_id,name,description,created_at,is_public,legacy_migrated) VALUES(?,?,?,?,?,?,1)',values)
            except sqlite3.IntegrityError as exc:
                raise ValueError("Notebook conflict or unregistered owner") from exc

    def get_notebook(self, ctx: RequestContext, notebook_id: str) -> Optional[dict]:
        self._identifier(notebook_id)
        with self._lock:
            self._require_open()
            row = self._conn.execute('SELECT '+self._columns+' FROM notebooks WHERE notebook_id=?',(notebook_id,)).fetchone()
            return self._row(row) if row else None

    def list_notebooks(self, ctx: RequestContext) -> list[dict]:
        with self._lock:
            self._require_open()
            return [self._row(row) for row in self._conn.execute('SELECT '+self._columns+' FROM notebooks ORDER BY notebook_id').fetchall()]

    def migrate_notebook(self, ctx: RequestContext, metadata: dict, members: list[dict]) -> None:
        values = self._metadata(metadata)
        if not isinstance(members,list): raise ValueError("Invalid legacy members")
        normalized = []
        for member in members:
            if not isinstance(member,dict): raise ValueError("Invalid legacy member")
            normalized.append((self._identifier(member.get('user_id')),self._identifier(member.get('role'))))
        if len({uid for uid, _ in normalized}) != len(normalized): raise ValueError("Duplicate legacy member")
        with self._lock:
            self._require_open()
            try:
                with self._conn:
                    self._conn.execute('BEGIN IMMEDIATE')
                    row = self._conn.execute('SELECT legacy_migrated,acl_revision FROM notebooks WHERE notebook_id=?',(values[0],)).fetchone()
                    if row and (row[0] or row[1]): return
                    if any(not self._conn.execute('SELECT 1 FROM roles WHERE role_id=?',(role,)).fetchone() for _,role in normalized):
                        raise ValueError("Invalid legacy role")
                    for uid in [values[1]]+[uid for uid,_ in normalized]:
                        self._conn.execute("INSERT OR IGNORE INTO users VALUES(?,datetime('now'),datetime('now'))",(uid,))
                    if not row:
                        self._conn.execute('INSERT INTO notebooks(notebook_id,owner_user_id,name,description,created_at,is_public) VALUES(?,?,?,?,?,?)',values)
                    self._conn.executemany('INSERT INTO notebook_members VALUES(?,?,?)',[(values[0],uid,role) for uid,role in normalized])
                    self._conn.execute('UPDATE notebooks SET legacy_migrated=1 WHERE notebook_id=?',(values[0],))
            except sqlite3.IntegrityError as exc:
                raise ValueError("Invalid legacy relations") from exc

    def membership_snapshot(self, ctx: RequestContext, notebook_id: str) -> dict:
        self._identifier(notebook_id)
        with self._lock:
            self._require_open()
            rows = self._conn.execute('SELECT n.acl_revision,n.is_public,n.archived,m.user_id,m.role_id FROM notebooks n LEFT JOIN notebook_members m ON m.notebook_id=n.notebook_id WHERE n.notebook_id=? ORDER BY m.user_id',(notebook_id,)).fetchall()
            if not rows: raise ValueError("Notebook does not exist")
            return {'revision':rows[0][0], 'is_public':bool(rows[0][1]), 'archived':bool(rows[0][2]),'members':[{'user_id':row[3],'role':row[4]} for row in rows if row[3] is not None]}

    def role_permissions(self, ctx: RequestContext, role: str) -> list[str]:
        self._identifier(role)
        with self._lock:
            self._require_open()
            return [row[0] for row in self._conn.execute('SELECT permission_id FROM role_permissions WHERE role_id=? ORDER BY permission_id',(role,)).fetchall()]

    def _change_member(self, notebook_id, user_id, role, expected_revision) -> bool:
        self._identifier(notebook_id); self._identifier(user_id)
        if type(expected_revision) is not int or expected_revision < 0: raise ValueError("Invalid revision")
        if role is not None: self._identifier(role)
        with self._lock:
            self._require_open()
            try:
                with self._conn:
                    self._conn.execute('BEGIN IMMEDIATE')
                    exists = self._conn.execute('SELECT 1 FROM notebooks WHERE notebook_id=?',(notebook_id,)).fetchone()
                    if not exists: raise ValueError("Notebook does not exist")
                    if not self._conn.execute('SELECT 1 FROM users WHERE user_id=?',(user_id,)).fetchone():
                        raise ValueError("User must first sign in")
                    count = self._conn.execute('UPDATE notebooks SET acl_revision=acl_revision+1 WHERE notebook_id=? AND acl_revision=?',(notebook_id,expected_revision)).rowcount
                    if not count: return False
                    if role is None:
                        self._conn.execute('DELETE FROM notebook_members WHERE notebook_id=? AND user_id=?',(notebook_id,user_id))
                    else:
                        self._conn.execute('INSERT INTO notebook_members VALUES(?,?,?) ON CONFLICT(notebook_id,user_id) DO UPDATE SET role_id=excluded.role_id',(notebook_id,user_id,role))
            except sqlite3.IntegrityError as exc:
                raise ValueError("Unknown role or relation") from exc
            return True

    def put_member(self, ctx: RequestContext, notebook_id: str, user_id: str, role: str, expected_revision: int) -> bool:
        return self._change_member(notebook_id,user_id,role,expected_revision)

    def delete_member(self, ctx: RequestContext, notebook_id: str, user_id: str, expected_revision: int) -> bool:
        return self._change_member(notebook_id,user_id,None,expected_revision)

    def update_notebook(self, ctx: RequestContext, notebook_id: str, name: str, description: str) -> None:
        self._identifier(notebook_id)
        if not isinstance(name,str) or not 0 < len(name.strip()) <= 80 or not isinstance(description,str) or len(description)>300:
            raise ValueError("Invalid notebook name or description")
        with self._lock:
            self._require_open()
            with self._conn:
                if not self._conn.execute('UPDATE notebooks SET name=?,description=? WHERE notebook_id=? AND is_public=0 AND archived=0',(name.strip(),description.strip(),notebook_id)).rowcount:
                    raise ValueError("Notebook is absent, public or archived")

    def set_archived(self, ctx: RequestContext, notebook_id: str, archived: bool) -> None:
        self._identifier(notebook_id)
        if type(archived) is not bool: raise ValueError("Invalid archive flag")
        with self._lock:
            self._require_open()
            with self._conn:
                if not self._conn.execute('UPDATE notebooks SET archived=?,acl_revision=acl_revision+1 WHERE notebook_id=? AND is_public=0',(int(archived),notebook_id)).rowcount:
                    raise ValueError("Notebook is absent or public")


__all__ = ["NotebookStore", "SqliteVectorStore", "StateStore", "Storage", "make_storage"]
