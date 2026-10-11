# cython: annotation_typing=False
from __future__ import annotations
import json, os, sqlite3, threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from core_specifications import NotebookStorePort, MemoryStorePort, RequestContext, StateStorePort, VectorStore
from memory import MemoryStore
from storage import NotebookStore, SqliteVectorStore, StateStore, ensure_database_schema
__version__="0.3.0"
class DataService:
    """Owns one SQLite connection shared by the database-domain stores."""
    def __init__(self,database_path:str)->None:
        if not isinstance(database_path,str) or not database_path.strip(): raise ValueError("database_path must be non-empty")
        self._database_path=database_path; self._conn=None; self._lock=threading.RLock(); self._closed=False
        self._memory=None; self._vectors=None; self._state=None; self._notebooks=None
    def _require_open(self):
        if self._closed: raise RuntimeError("data service is closed")
    def initialize(self,ctx:RequestContext)->None:
        with self._lock:
            self._require_open()
            if self._conn is not None: return
            if self._database_path != ":memory:": os.makedirs(os.path.dirname(self._database_path) or ".",exist_ok=True)
            conn=sqlite3.connect(self._database_path,check_same_thread=False,timeout=10); conn.row_factory=sqlite3.Row; conn.execute("PRAGMA foreign_keys=ON")
            try:
                ensure_database_schema(conn)
                self._memory=MemoryStore(conn,self._lock); self._vectors=SqliteVectorStore(conn,self._lock)
                self._state=StateStore(conn,self._lock); self._notebooks=NotebookStore(conn,self._lock); self._conn=conn
            except BaseException:
                conn.close(); self._memory=self._vectors=self._state=self._notebooks=None; raise
    def memory_store(self,ctx):
        with self._lock: self.initialize(ctx); return self._memory
    def vector_store(self,ctx):
        with self._lock: self.initialize(ctx); return self._vectors
    def state_db(self,ctx):
        with self._lock: self.initialize(ctx); return self._state
    def notebook_store(self,ctx):
        with self._lock: self.initialize(ctx); return self._notebooks
    def _db(self,ctx): self.initialize(ctx); return self._conn
    @staticmethod
    def _user_record(row):
        if row is None: return None
        user=dict(row)
        for key in ("is_admin","is_guest","is_active"): user[key]=bool(user[key])
        return user
    def get_user(self,ctx,user_id):
        with self._lock:
            row=self._db(ctx).execute("SELECT id,username,password_hash,is_admin,is_guest,is_active,quota_date,quota_used FROM users WHERE id=?",(user_id,)).fetchone(); return self._user_record(row)
    def get_user_by_username(self,ctx,username):
        with self._lock:
            row=self._db(ctx).execute("SELECT id,username,password_hash,is_admin,is_guest,is_active,quota_date,quota_used FROM users WHERE username=?",(username,)).fetchone(); return self._user_record(row)
    def create_user(self,ctx,user):
        if not isinstance(user,dict): raise ValueError("user must be a dictionary")
        uid,username=user.get("id",user.get("user_id")),user.get("username")
        if not isinstance(uid,str) or not uid.strip() or not isinstance(username,str) or not username.strip(): raise ValueError("user id and username are required")
        flags={"is_admin":user.get("is_admin",0),"is_guest":user.get("is_guest",0),"is_active":user.get("is_active",1)}
        if any(type(v) not in (int,bool) or int(v) not in (0,1) for v in flags.values()): raise ValueError("user flags must be boolean")
        with self._lock:
            conn=self._db(ctx)
            try:
                with conn: conn.execute("INSERT INTO users(id,username,password_hash,is_admin,is_guest,is_active,quota_used) VALUES(?,?,?,?,?,?,0)",(uid,username,user.get("password_hash"),int(flags["is_admin"]),int(flags["is_guest"]),int(flags["is_active"])))
            except sqlite3.IntegrityError as exc: raise ValueError("user id or username already exists") from exc
            return {k:v for k,v in self.get_user(ctx,uid).items() if k!="password_hash"}
    def list_users(self,ctx,active_only=True):
        with self._lock:
            sql="SELECT id,username,password_hash,is_admin,is_guest,is_active,quota_date,quota_used FROM users"+(" WHERE is_active=1" if active_only else "")+" ORDER BY username"
            return [{k:v for k,v in self._user_record(r).items() if k!="password_hash"} for r in self._db(ctx).execute(sql)]
    def set_user_active(self,ctx,user_id,active):
        if type(active) is not bool: raise ValueError("active must be boolean")
        with self._lock,self._db(ctx):
            if not self._conn.execute("UPDATE users SET is_active=? WHERE id=?",(int(active),user_id)).rowcount: raise ValueError("user not found")
    def reserve_site_quota(self,ctx,local_date,limit):
        if not isinstance(local_date,str): raise ValueError("local_date must be YYYY-MM-DD")
        try:
            if datetime.fromisoformat(local_date).date().isoformat()!=local_date: raise ValueError
        except ValueError: raise ValueError("local_date must be YYYY-MM-DD") from None
        if isinstance(limit,bool) or not isinstance(limit,int) or limit<1: raise ValueError("limit must be positive")
        with self._lock:
            conn=self._db(ctx)
            with conn:
                conn.execute("BEGIN IMMEDIATE")
                user=conn.execute("SELECT quota_date,quota_used FROM users WHERE id=?",(ctx.user_id,)).fetchone()
                if user is None: raise ValueError("quota user is not registered")
                used=conn.execute("SELECT COALESCE(SUM(CASE WHEN quota_date=? THEN quota_used ELSE 0 END),0) FROM users",(local_date,)).fetchone()[0]
                if used>=limit: return None
                current=user["quota_used"] if user["quota_date"]==local_date else 0
                current+=1
                conn.execute("UPDATE users SET quota_date=?,quota_used=? WHERE id=?",(local_date,current,ctx.user_id))
                return used+1
    def site_quota_used(self,ctx,local_date):
        try:
            if datetime.fromisoformat(local_date).date().isoformat()!=local_date: raise ValueError
        except (TypeError,ValueError): raise ValueError("local_date must be YYYY-MM-DD") from None
        with self._lock:
            row=self._db(ctx).execute("SELECT COALESCE(SUM(CASE WHEN quota_date=? THEN quota_used ELSE 0 END),0) FROM users",(local_date,)).fetchone(); return int(row[0])
    def save_conversation(self,ctx,conversation):
        if not isinstance(conversation,dict): raise ValueError("conversation must be a dictionary")
        cid=conversation.get("id",conversation.get("conversation_id")); user_id=conversation.get("user_id",ctx.user_id)
        if user_id!=ctx.user_id: raise PermissionError("conversation belongs to another user")
        if not isinstance(cid,str) or not cid.strip(): raise ValueError("conversation id required")
        scope=conversation.get("notebook_id",conversation.get("scope",[]))
        if isinstance(scope,list): scope=json.dumps(sorted(set(scope)),ensure_ascii=False)
        elif isinstance(scope,str):
            try: parsed=json.loads(scope)
            except ValueError: raise ValueError("notebook scope must be a JSON list") from None
            if not isinstance(parsed,list) or any(not isinstance(item,str) for item in parsed): raise ValueError("notebook scope must be a JSON list of strings")
            scope=json.dumps(sorted(set(parsed)),ensure_ascii=False)
        else: raise ValueError("notebook scope must be a list or JSON string")
        messages=json.dumps(conversation.get("messages",[]),ensure_ascii=False,allow_nan=False)
        title=conversation.get("title","")
        if not isinstance(title,str): raise ValueError("conversation title must be text")
        updated=conversation.get("updated_at") or datetime.now(timezone.utc).isoformat()
        with self._lock:
            conn=self._db(ctx)
            with conn: conn.execute("INSERT INTO conversations(id,user_id,notebook_id,title,messages,updated_at) VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET notebook_id=excluded.notebook_id,title=excluded.title,messages=excluded.messages,updated_at=excluded.updated_at WHERE conversations.user_id=excluded.user_id",(cid,ctx.user_id,scope,title,messages,updated))
            row=conn.execute("SELECT user_id FROM conversations WHERE id=?",(cid,)).fetchone()
            if not row or row[0]!=ctx.user_id: raise PermissionError("conversation belongs to another user")
        return self.get_conversation(ctx,cid,ctx.user_id)
    def get_conversation(self,ctx,conversation_id,user_id):
        if user_id!=ctx.user_id: raise PermissionError("conversation belongs to another user")
        with self._lock:
            r=self._db(ctx).execute("SELECT id,user_id,notebook_id,title,messages,updated_at FROM conversations WHERE user_id=? AND id=?",(user_id,conversation_id)).fetchone()
            if not r:return None
            result=dict(r); result["messages"]=json.loads(result["messages"]); result["notebook_id"]=json.loads(result["notebook_id"]); return result
    def list_conversations(self,ctx,user_id,notebook_id=None):
        if user_id!=ctx.user_id: raise PermissionError("conversation belongs to another user")
        with self._lock:
            if notebook_id is None:
                rows=self._db(ctx).execute("SELECT id,user_id,notebook_id,title,messages,updated_at FROM conversations WHERE user_id=? ORDER BY updated_at DESC",(user_id,)).fetchall()
            else:
                if isinstance(notebook_id,list): notebook_id=json.dumps(sorted(set(notebook_id)),ensure_ascii=False)
                elif isinstance(notebook_id,str):
                    try: parsed=json.loads(notebook_id)
                    except ValueError: raise ValueError("notebook_id must be a scope JSON list") from None
                    if not isinstance(parsed,list) or any(not isinstance(item,str) for item in parsed): raise ValueError("notebook_id must be a scope JSON list")
                    notebook_id=json.dumps(sorted(set(parsed)),ensure_ascii=False)
                else: raise ValueError("notebook_id must be None or a scope list")
                rows=self._db(ctx).execute("SELECT id,user_id,notebook_id,title,messages,updated_at FROM conversations WHERE user_id=? AND notebook_id=? ORDER BY updated_at DESC",(user_id,notebook_id)).fetchall()
            result=[]
            for r in rows:
                item=dict(r); item["messages"]=json.loads(item["messages"]); item["notebook_id"]=json.loads(item["notebook_id"]); result.append(item)
            return result
    def delete_conversation(self,ctx,conversation_id,user_id):
        if user_id!=ctx.user_id: raise PermissionError("conversation belongs to another user")
        with self._lock,self._db(ctx): self._conn.execute("DELETE FROM conversations WHERE user_id=? AND id=?",(user_id,conversation_id))
    def create_notebook(self,ctx,metadata):
        self.notebook_store(ctx).create_notebook(ctx,metadata)
        return self.notebook_store(ctx).get_notebook(ctx,metadata["id"])
    def get_notebook(self,ctx,notebook_id): return self.notebook_store(ctx).get_notebook(ctx,notebook_id)
    def list_notebooks(self,ctx,user_id):
        if user_id!=ctx.user_id: raise PermissionError("notebooks belong to another user")
        return [book for book in self.notebook_store(ctx).list_notebooks(ctx) if book["owner_user_id"]==user_id or any(m["user_id"]==user_id for m in self.list_members(ctx,book["id"]))]
    def membership_snapshot(self,ctx,notebook_id): return self.notebook_store(ctx).membership_snapshot(ctx,notebook_id)
    def list_members(self,ctx,notebook_id): return self.notebook_store(ctx).list_members(ctx,notebook_id)
    def put_member(self,ctx,notebook_id,user_id,role): return self.notebook_store(ctx).put_member(ctx,notebook_id,user_id,role)
    def delete_member(self,ctx,notebook_id,user_id): return self.notebook_store(ctx).delete_member(ctx,notebook_id,user_id)
    def update_notebook(self,ctx,notebook_id,name): return self.notebook_store(ctx).update_notebook(ctx,notebook_id,name)
    def delete_notebook(self,ctx,notebook_id): return self.notebook_store(ctx).delete_notebook(ctx,notebook_id)
    def get_agent_data(self,ctx,data_type,name):
        with self._lock:
            row=self._db(ctx).execute("SELECT content,updated_at FROM agent_data WHERE type=? AND name=?",(data_type,name)).fetchone()
            return dict(row) if row else None
    def set_agent_data(self,ctx,data_type,name,content):
        if not all(isinstance(x,str) and x for x in (data_type,name)): raise ValueError("type and name are required")
        if not isinstance(content,str): raise ValueError("agent data content must be text")
        encoded=content
        with self._lock,self._db(ctx):
            self._conn.execute("INSERT INTO agent_data VALUES(?,?,?,?,?) ON CONFLICT(type,name) DO UPDATE SET content=excluded.content,updated_at=excluded.updated_at",(__import__("uuid").uuid4().hex,data_type,name,encoded,datetime.now(timezone.utc).isoformat()))
    def list_agent_data(self,ctx,data_type):
        with self._lock:
            return [dict(r) for r in self._db(ctx).execute("SELECT type,name,content,updated_at FROM agent_data WHERE type=? ORDER BY name",(data_type,))]
    def close(self,ctx):
        with self._lock:
            if self._closed:return
            self._closed=True
            for store in (self._notebooks,self._state,self._vectors,self._memory):
                if store is not None: store.close()
            if self._conn is not None:self._conn.close(); self._conn=None
__all__=["DataService"]