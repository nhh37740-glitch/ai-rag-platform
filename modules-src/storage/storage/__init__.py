# cython: annotation_typing=False
from __future__ import annotations
import json, math, os, sqlite3, threading, uuid
from datetime import datetime, timezone
from typing import Any, List, Optional
from core_specifications import MemoryEntry, MemoryStorePort, RequestContext, VectorStore
__version__ = "0.5.0"
_SCHEMA = {
"users": "id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE, password_hash TEXT, is_admin INTEGER NOT NULL DEFAULT 0, is_guest INTEGER NOT NULL DEFAULT 0, is_active INTEGER NOT NULL DEFAULT 1, quota_date TEXT, quota_used INTEGER NOT NULL DEFAULT 0",
"notebooks": "id TEXT PRIMARY KEY, owner_user_id TEXT NOT NULL REFERENCES users(id), name TEXT NOT NULL, created_at TEXT NOT NULL",
"notebook_members": "notebook_id TEXT NOT NULL REFERENCES notebooks(id) ON DELETE CASCADE, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, role TEXT NOT NULL CHECK(role IN ('editor','viewer')), PRIMARY KEY(notebook_id,user_id)",
"documents": "id TEXT PRIMARY KEY, document_id TEXT NOT NULL, notebook_id TEXT NOT NULL, file_name TEXT NOT NULL, chunk_index INTEGER NOT NULL, content TEXT NOT NULL, embedding TEXT NOT NULL, UNIQUE(document_id,chunk_index)",
"conversations": "id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), notebook_id TEXT NOT NULL, title TEXT NOT NULL, messages TEXT NOT NULL, updated_at TEXT NOT NULL",
"agent_data": "id TEXT PRIMARY KEY, type TEXT NOT NULL, name TEXT NOT NULL, content TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(type,name)",
}
TABLES = frozenset(_SCHEMA)
_COLUMNS = {"users": ["id","username","password_hash","is_admin","is_guest","is_active","quota_date","quota_used"], "notebooks": ["id","owner_user_id","name","created_at"], "notebook_members": ["notebook_id","user_id","role"], "documents": ["id","document_id","notebook_id","file_name","chunk_index","content","embedding"], "conversations": ["id","user_id","notebook_id","title","messages","updated_at"], "agent_data": ["id","type","name","content","updated_at"]}
def ensure_database_schema(conn):
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
    if names:
        if names != TABLES: raise RuntimeError("database schema does not match the six-table contract")
        for table, expected in _COLUMNS.items():
            info = list(conn.execute(f'PRAGMA table_info("{table}")'))
            actual = [r[1] for r in info]
            if actual != expected: raise RuntimeError(f"database schema mismatch in {table}")
            pk = [r[1] for r in sorted((r for r in info if r[5]), key=lambda r:r[5])]
            expected_pk = ["notebook_id","user_id"] if table == "notebook_members" else ["id"]
            if pk != expected_pk: raise RuntimeError(f"database primary key mismatch in {table}")
        def unique_keys(table):
            keys=[]
            for index in conn.execute(f'PRAGMA index_list("{table}")'):
                if index[2]: keys.append(tuple(r[2] for r in conn.execute(f'PRAGMA index_info("{index[1]}")')))
            return set(keys)
        if ("username",) not in unique_keys("users"): raise RuntimeError("database unique key mismatch in users")
        if ("document_id","chunk_index") not in unique_keys("documents"): raise RuntimeError("database unique key mismatch in documents")
        if ("type","name") not in unique_keys("agent_data"): raise RuntimeError("database unique key mismatch in agent_data")
        if ("notebook_id","user_id") not in unique_keys("notebook_members"): raise RuntimeError("database unique key mismatch in notebook_members")
        def foreign_keys(table):
            return {(r[2],r[3],r[4]) for r in conn.execute(f'PRAGMA foreign_key_list("{table}")')}
        if foreign_keys("notebooks") != {("users","owner_user_id","id")} : raise RuntimeError("database foreign key mismatch in notebooks")
        if foreign_keys("notebook_members") != {("notebooks","notebook_id","id"),("users","user_id","id")}: raise RuntimeError("database foreign key mismatch in notebook_members")
        if foreign_keys("conversations") != {("users","user_id","id")}: raise RuntimeError("database foreign key mismatch in conversations")
        role_sql=conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='notebook_members'").fetchone()[0]
        compact="".join(role_sql.lower().replace('"','').split())
        if "check(rolein('editor','viewer'))" not in compact: raise RuntimeError("database role constraint mismatch")
        return
    with conn:
        conn.execute("BEGIN IMMEDIATE")
        for table, definition in _SCHEMA.items(): conn.execute(f"CREATE TABLE {table} ({definition})")

def _vector(value):
    if isinstance(value, (str, bytes)):
        raise ValueError("embedding must be a non-empty one-dimensional finite vector")
    try:
        vector = [float(item) for item in value]
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("embedding must contain finite numbers") from exc
    if not vector or any(not math.isfinite(item) for item in vector):
        raise ValueError("embedding must be a non-empty one-dimensional finite vector")
    return vector
def _top_k(value):
    if isinstance(value,bool) or not isinstance(value,int): raise TypeError("top_k must be an integer")
    if value<1: raise ValueError("top_k must be positive")

class _SqliteStore:
    def __init__(self, db_path, lock=None):
        self._owns_conn = not isinstance(db_path,sqlite3.Connection)
        if self._owns_conn:
            if str(db_path) != ":memory:": os.makedirs(os.path.dirname(str(db_path)) or ".",exist_ok=True)
            self._conn=sqlite3.connect(str(db_path),check_same_thread=False,timeout=10)
            self._conn.row_factory=sqlite3.Row; self._conn.execute("PRAGMA foreign_keys=ON")
            try: ensure_database_schema(self._conn)
            except BaseException: self._conn.close(); raise
        else: self._conn=db_path
        self._lock=lock or threading.RLock(); self._closed=False
    def _require_open(self):
        if self._closed: raise RuntimeError("store is closed")
    def close(self):
        with self._lock:
            if not self._closed:
                if self._owns_conn: self._conn.close()
                self._closed=True

class SqliteVectorStore(_SqliteStore):
    def add(self,source_id,chunks,embeddings):
        with self._lock:
            self._require_open()
            if not isinstance(source_id,str) or not source_id.strip(): raise ValueError("source_id must be non-empty")
            texts,raw=list(chunks),list(embeddings)
            if len(texts)!=len(raw): raise ValueError("chunk and embedding counts must match")
            if any(not isinstance(x,str) for x in texts): raise TypeError("chunks must contain strings")
            vectors=[_vector(x) for x in raw]
            if len({len(v) for v in vectors})>1: raise ValueError("embedding dimensions must match")
            dims={len(_vector(json.loads(r[0]))) for r in self._conn.execute("SELECT embedding FROM documents")}
            if vectors and any(d!=len(vectors[0]) for d in dims): raise ValueError("embedding dimension differs from the stored collection")
            notebook,sep,doc=source_id.partition("/")
            if not sep: notebook,doc="",source_id
            rows=[(uuid.uuid4().hex,source_id,notebook,doc.rsplit("/",1)[-1],i,text,json.dumps(v,allow_nan=False)) for i,(text,v) in enumerate(zip(texts,vectors))]
            with self._conn:
                self._conn.execute("DELETE FROM documents WHERE document_id=?",(source_id,))
                self._conn.executemany("INSERT INTO documents VALUES(?,?,?,?,?,?,?)",rows)
    def search(self,embedding,top_k=5,scopes=None):
        with self._lock:
            self._require_open(); _top_k(top_k); query=_vector(embedding)
            if scopes==[]: return []
            hits=[]
            for row in self._conn.execute("SELECT document_id,content,embedding,notebook_id FROM documents ORDER BY rowid"):
                if scopes is not None and row["notebook_id"] not in scopes: continue
                v=_vector(json.loads(row["embedding"]))
                if len(v)!=len(query): raise ValueError("query embedding dimension differs from stored vector")
                score=float(sum(a*b for a,b in zip(v,query)))
                if not math.isfinite(score): raise ValueError("vector score is not finite")
                hits.append((row["document_id"],row["content"],score))
            return sorted(hits,key=lambda x:-x[2])[:top_k]
    def list_documents(self,scopes=None):
        with self._lock:
            self._require_open()
            rows=self._conn.execute("SELECT document_id,COUNT(*) n,notebook_id FROM documents GROUP BY document_id,notebook_id ORDER BY document_id")
            return [(r["document_id"],r["n"]) for r in rows if scopes is None or r["notebook_id"] in scopes]
    def document_chunks(self,source_id):
        with self._lock:
            self._require_open(); return [r[0] for r in self._conn.execute("SELECT content FROM documents WHERE document_id=? ORDER BY chunk_index",(source_id,))]

class StateStore(_SqliteStore):
    def get(self,ctx,key):
        with self._lock:
            self._require_open(); row=self._conn.execute("SELECT content FROM agent_data WHERE type=? AND name=?",("state:"+ctx.user_id,key)).fetchone()
            return json.loads(row[0]) if row else None
    def set(self,ctx,key,value):
        self._require_open(); payload=json.dumps(value,ensure_ascii=False,allow_nan=False); self._put("state:"+ctx.user_id,key,payload)
    def _put(self,kind,name,content):
        with self._lock,self._conn:
            self._require_open(); self._conn.execute("INSERT INTO agent_data VALUES(?,?,?,?,?) ON CONFLICT(type,name) DO UPDATE SET content=excluded.content,updated_at=excluded.updated_at",(uuid.uuid4().hex,kind,name,content,datetime.now(timezone.utc).isoformat()))
    def delete(self,ctx,key):
        self._require_open()
        with self._lock,self._conn:
            self._conn.execute("DELETE FROM agent_data WHERE type=? AND name=?",("state:"+ctx.user_id,key))
    def increment_if_below(self,ctx,key,limit):
        if not isinstance(key,str) or not key.strip(): raise ValueError("counter key must be non-empty")
        if isinstance(limit,bool) or not isinstance(limit,int) or limit<1: raise ValueError("counter limit must be a positive integer")
        with self._lock:
            self._require_open()
            with self._conn:
                self._conn.execute("BEGIN IMMEDIATE"); row=self._conn.execute("SELECT content FROM agent_data WHERE type=? AND name=?",("state:"+ctx.user_id,key)).fetchone()
                used=json.loads(row[0]) if row else 0
                if type(used) is not int or used<0: raise ValueError("counter must be a non-negative integer")
                if used>=limit: return None
                used+=1; self._conn.execute("INSERT INTO agent_data VALUES(?,?,?,?,?) ON CONFLICT(type,name) DO UPDATE SET content=excluded.content,updated_at=excluded.updated_at",(uuid.uuid4().hex,"state:"+ctx.user_id,key,json.dumps(used),datetime.now(timezone.utc).isoformat())); return used

class NotebookStore(_SqliteStore):
    def register_user(self,ctx,user_id):
        with self._lock,self._conn:
            self._require_open(); self._conn.execute("INSERT OR IGNORE INTO users(id,username,is_active) VALUES(?,?,1)",(user_id,user_id))
    def list_users(self,ctx):
        with self._lock:
            self._require_open(); return [dict(r) for r in self._conn.execute("SELECT id AS user_id,username,is_admin,is_guest,is_active FROM users ORDER BY username")]
    def create_notebook(self,ctx,metadata):
        if not isinstance(metadata,dict): raise ValueError("Invalid notebook metadata")
        bid=metadata.get("id"); owner=metadata.get("owner_user_id") or ctx.user_id; name=metadata.get("name"); created=metadata.get("created_at") or datetime.now(timezone.utc).isoformat()
        if not all(isinstance(v,str) and v.strip() for v in (bid,owner,name,created)): raise ValueError("Invalid notebook metadata")
        self._require_open()
        with self._lock,self._conn:
            account=self._conn.execute("SELECT is_guest FROM users WHERE id=?",(owner,)).fetchone()
            if account is None or account[0]: raise ValueError("Notebook owner must be a registered non-guest user")
            try: self._conn.execute("INSERT INTO notebooks VALUES(?,?,?,?)",(bid,owner,name.strip(),created))
            except sqlite3.IntegrityError as exc: raise ValueError("Notebook conflict or unknown owner") from exc
    def get_notebook(self,ctx,notebook_id):
        with self._lock:
            self._require_open(); r=self._conn.execute("SELECT id,owner_user_id,name,created_at FROM notebooks WHERE id=?",(notebook_id,)).fetchone(); return dict(r) if r else None
    def list_notebooks(self,ctx):
        with self._lock:
            self._require_open(); return [dict(r) for r in self._conn.execute("SELECT id,owner_user_id,name,created_at FROM notebooks ORDER BY id")]
    def membership_snapshot(self,ctx,notebook_id):
        with self._lock:
            self._require_open(); r=self._conn.execute("SELECT owner_user_id FROM notebooks WHERE id=?",(notebook_id,)).fetchone()
            if not r: raise ValueError("Notebook does not exist")
            members=[dict(m) for m in self._conn.execute("SELECT user_id,role FROM notebook_members WHERE notebook_id=? ORDER BY user_id",(notebook_id,))]
            return {"owner_user_id":r[0],"members":members}
    def put_member(self,ctx,notebook_id,user_id,role):
        if role not in {"editor","viewer"}: raise ValueError("role must be editor or viewer")
        self._require_open()
        with self._lock,self._conn:
            owner=self._conn.execute("SELECT owner_user_id FROM notebooks WHERE id=?",(notebook_id,)).fetchone()
            account=self._conn.execute("SELECT is_guest FROM users WHERE id=?",(user_id,)).fetchone()
            if owner is None or account is None or owner[0]==user_id or (account[0] and role!="viewer"): raise ValueError("Member must be a registered non-owner; guests may only be viewers")
            try: self._conn.execute("INSERT INTO notebook_members VALUES(?,?,?) ON CONFLICT(notebook_id,user_id) DO UPDATE SET role=excluded.role",(notebook_id,user_id,role))
            except sqlite3.IntegrityError as exc: raise ValueError("Unknown notebook or user") from exc
    def list_members(self,ctx,notebook_id):
        with self._lock:
            self._require_open()
            if not self._conn.execute("SELECT 1 FROM notebooks WHERE id=?",(notebook_id,)).fetchone(): raise ValueError("Notebook does not exist")
            return [dict(r) for r in self._conn.execute("SELECT user_id,role FROM notebook_members WHERE notebook_id=? ORDER BY user_id",(notebook_id,))]
    def update_notebook(self,ctx,notebook_id,name):
        if not isinstance(name,str) or not name.strip(): raise ValueError("name required")
        self._require_open()
        with self._lock,self._conn:
            if not self._conn.execute("UPDATE notebooks SET name=? WHERE id=?",(name.strip(),notebook_id)).rowcount: raise ValueError("Notebook does not exist")
    def delete_notebook(self,ctx,notebook_id):
        self._require_open()
        with self._lock,self._conn:
            if not self._conn.execute("SELECT 1 FROM notebooks WHERE id=?",(notebook_id,)).fetchone(): raise ValueError("Notebook does not exist")
            self._conn.execute("DELETE FROM documents WHERE notebook_id=?",(notebook_id,))
            rows=self._conn.execute("SELECT id,notebook_id FROM conversations").fetchall()
            for row in rows:
                try: scopes=json.loads(row["notebook_id"])
                except (ValueError,TypeError): scopes=[]
                if notebook_id in scopes: self._conn.execute("DELETE FROM conversations WHERE id=?",(row["id"],))
            self._conn.execute("DELETE FROM notebooks WHERE id=?",(notebook_id,))
    def delete_member(self,ctx,notebook_id,user_id):
        with self._lock,self._conn:
            self._require_open(); self._conn.execute("DELETE FROM notebook_members WHERE notebook_id=? AND user_id=?",(notebook_id,user_id))


__all__=["NotebookStore","SqliteVectorStore","StateStore","ensure_database_schema"]
