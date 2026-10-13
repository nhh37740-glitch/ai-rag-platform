# cython: annotation_typing=False
from __future__ import annotations
import json, os, sqlite3, threading, uuid
from datetime import datetime, timezone
from typing import List, Optional
from core_specifications import MemoryEntry, RequestContext
from storage import ensure_database_schema
__version__="0.3.0"
class MemoryStore:
    """Memory facade backed by the shared agent_data table."""
    def __init__(self, db_path, lock=None):
        self._owns_conn=not isinstance(db_path,sqlite3.Connection)
        if self._owns_conn:
            if str(db_path) != ":memory:": os.makedirs(os.path.dirname(str(db_path)) or ".",exist_ok=True)
            self._conn=sqlite3.connect(str(db_path),check_same_thread=False,timeout=10); self._conn.row_factory=sqlite3.Row
            self._conn.execute("PRAGMA foreign_keys=ON")
            try: ensure_database_schema(self._conn)
            except BaseException: self._conn.close(); raise
        else: self._conn=db_path
        self._lock=lock or threading.RLock(); self._closed=False
    def _ctx(self,ctx):
        if self._closed: raise RuntimeError("memory store is closed")
        if ctx is None: raise ValueError("ctx required")
        return ctx
    @staticmethod
    def _type(ctx,namespace): return "memory:"+str(namespace)+":"+ctx.user_id
    @staticmethod
    def _entry(raw): return MemoryEntry(**json.loads(raw))
    def write(self,ctx,namespace,key,content,importance=0.0):
        with self._lock:
            c=self._ctx(ctx); entry=MemoryEntry(uuid.uuid4().hex,namespace,key,content,datetime.now(timezone.utc).isoformat(),importance)
            payload=json.dumps(entry.__dict__,ensure_ascii=False,allow_nan=False)
            with self._conn:
                self._conn.execute("INSERT INTO agent_data VALUES(?,?,?,?,?) ON CONFLICT(type,name) DO UPDATE SET content=excluded.content,updated_at=excluded.updated_at",(uuid.uuid4().hex,self._type(c,namespace),key,payload,entry.created))
            return entry
    def get(self,ctx,namespace,key):
        with self._lock:
            c=self._ctx(ctx); row=self._conn.execute("SELECT content FROM agent_data WHERE type=? AND name=?",(self._type(c,namespace),key)).fetchone()
            return self._entry(row[0]) if row else None
    def search(self,ctx,namespace,query,top_k=5):
        with self._lock:
            c=self._ctx(ctx)
            if isinstance(top_k,bool) or not isinstance(top_k,int): raise TypeError("top_k must be an integer")
            if top_k<1: raise ValueError("top_k must be positive")
            rows=self._conn.execute("SELECT content FROM agent_data WHERE type=?",(self._type(c,namespace),)).fetchall()
            terms=[term for term in query.replace("？"," ").replace("?"," ").split() if term]
            scored=[]
            for row in rows:
                entry=self._entry(row[0]); score=sum(1 for term in terms if term in entry.content)+entry.importance; scored.append((score,entry))
            scored.sort(key=lambda item:-item[0]); return [entry for _,entry in scored[:top_k]]
    def forget(self,ctx,namespace,key):
        c=self._ctx(ctx)
        with self._lock,self._conn:
            self._conn.execute("DELETE FROM agent_data WHERE type=? AND name=?",(self._type(c,namespace),key))
    def close(self):
        with self._lock:
            if not self._closed:
                if self._owns_conn: self._conn.close()
                self._closed=True
def make_memory(db_path): return MemoryStore(db_path)
__all__=["MemoryStore","make_memory"]