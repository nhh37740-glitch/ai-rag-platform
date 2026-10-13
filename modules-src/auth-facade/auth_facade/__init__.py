# cython: annotation_typing=False
# cython: infer_types=False
from __future__ import annotations
import re
import threading
import uuid
from datetime import datetime,timedelta,timezone
from auth_runtime import AuthRuntime
from core_specifications import AuthPrincipal,DataServicePort,RequestContext
__version__="0.5.1"
_USER_NAME=re.compile(r"[A-Za-z0-9_.-]{3,64}")
_NOTEBOOK_ID=re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
_PERMISSION_SET={"read","query","authenticated","create_notebook","manage_users","manage_models"}
def _valid_password(value):
    if not isinstance(value,str): return False
    try: size=len(value.encode("utf-8"))
    except UnicodeEncodeError: return False
    return 8<=size<=1024
def _public_user(user):
    return {k:user[k] for k in ("id","username","is_admin","is_guest","is_active") if k in user}
class AuthService:
    """Authentication, notebook authorization, and site-wide query quota."""
    def __init__(self,data:DataServicePort,session_ttl_seconds:int=43200,daily_limit:int=100):
        if type(session_ttl_seconds) is not int or not 1<=session_ttl_seconds<=43200: raise ValueError("Invalid session lifetime")
        if type(daily_limit) is not int or daily_limit<1: raise ValueError("Invalid daily limit")
        self._data=data; self._runtime=AuthRuntime(); self._session_ttl=session_ttl_seconds
        self._daily_limit=daily_limit; self._lock=threading.RLock()
        self._dummy_hash=self._runtime.hash_password("constant-time-dummy-password")
    def __repr__(self): return "AuthService(session_ttl_seconds=%r, daily_limit=%r)"%(self._session_ttl,self._daily_limit)
    def initialize(self,ctx:RequestContext,admin_username:str,admin_password:str)->None:
        self._data.initialize(ctx); users=self._data.list_users(ctx)
        if users: return
        self._validate_username(admin_username)
        if admin_username.lower()=="guest" or not _valid_password(admin_password): raise ValueError("Invalid bootstrap credentials")
        admin={"id":uuid.uuid4().hex,"username":admin_username,"password_hash":self._runtime.hash_password(admin_password),
               "is_admin":True,"is_guest":False,"is_active":True,"quota_date":"","quota_used":0}
        guest={"id":"guest","username":"guest","password_hash":None,"is_admin":False,"is_guest":True,"is_active":True,"quota_date":"","quota_used":0}
        with self._lock:
            if self._data.list_users(ctx): return
            self._data.create_user(ctx,admin); self._data.create_user(ctx,guest)
    @staticmethod
    def _validate_username(username):
        if not isinstance(username,str) or not _USER_NAME.fullmatch(username) or username.lower()=="guest": raise ValueError("Invalid username")
    def _user_by_id(self,ctx,user_id,active=True):
        user=self._data.get_user(ctx,user_id)
        if not isinstance(user,dict) or user.get("id")!=user_id or (active and user.get("is_active") is not True):
            raise PermissionError("Authentication denied")
        return user
    def _principal_user(self,ctx,principal):
        self._runtime.validate_principal(ctx,principal); user=self._user_by_id(ctx,principal.user_id)
        expected="guest" if user.get("is_guest") else "admin" if user.get("is_admin") else "user"
        if principal.role!=expected: raise PermissionError("Authentication denied")
        return user
    def _principal(self,ctx,user):
        role="guest" if user.get("is_guest") else "admin" if user.get("is_admin") else "user"
        return self._runtime.issue_principal(ctx,user["id"],role)
    def register(self,ctx:RequestContext,username:str,password:str)->dict:
        self._validate_username(username)
        if not _valid_password(password): raise ValueError("Invalid password")
        if self._data.get_user_by_username(ctx,username) is not None: raise ValueError("Username unavailable")
        user={"id":uuid.uuid4().hex,"username":username,"password_hash":self._runtime.hash_password(password),
              "is_admin":False,"is_guest":False,"is_active":True,"quota_date":"","quota_used":0}
        try: created=self._data.create_user(ctx,user)
        except (ValueError,KeyError): raise ValueError("Username unavailable") from None
        return _public_user(created if isinstance(created,dict) else user)
    def login(self,ctx:RequestContext,username:str,password:str)->tuple[AuthPrincipal,str]:
        user=self._data.get_user_by_username(ctx,username) if isinstance(username,str) else None
        encoded=user.get("password_hash") if isinstance(user,dict) else self._dummy_hash
        valid=self._runtime.verify_password(password,encoded) if isinstance(encoded,str) else False
        if not valid or not isinstance(user,dict) or user.get("is_guest") or user.get("is_active") is not True: raise PermissionError("Authentication denied")
        principal=self._principal(ctx,user); token=self._runtime.issue_session(ctx,user["id"],self._session_ttl)
        return principal,token
    def authenticate_session(self,ctx:RequestContext,token:str)->AuthPrincipal:
        user_id=self._runtime.resolve_session(ctx,token)
        if user_id is None: raise PermissionError("Authentication denied")
        return self._principal(ctx,self._user_by_id(ctx,user_id))
    def logout(self,ctx:RequestContext,token:str)->None: self._runtime.revoke_session(ctx,token)
    def guest(self,ctx:RequestContext)->AuthPrincipal:
        user=self._data.get_user_by_username(ctx,"guest")
        if not isinstance(user,dict) or user.get("is_guest") is not True or user.get("is_active") is not True: raise PermissionError("Guest unavailable")
        return self._principal(ctx,user)
    def authorize(self,ctx:RequestContext,principal:AuthPrincipal,permission:str)->None:
        if not isinstance(permission,str) or permission not in _PERMISSION_SET: raise ValueError("Unknown permission")
        user=self._principal_user(ctx,principal)
        if permission=="authenticated" and user.get("is_guest"): raise PermissionError("Authentication required")
        if permission=="create_notebook" and user.get("is_guest"): raise PermissionError("Permission denied")
        if permission in {"manage_users","manage_models"} and not user.get("is_admin"): raise PermissionError("Permission denied")
    def _notebook(self,ctx,notebook_id):
        if not isinstance(notebook_id,str) or not _NOTEBOOK_ID.fullmatch(notebook_id): raise ValueError("Invalid notebook identifier")
        record=self._data.get_notebook(ctx,notebook_id)
        return record if isinstance(record,dict) else None
    def allowed_notebooks(self,ctx:RequestContext,principal:AuthPrincipal,available_ids:list[str],public_ids:list[str]=[])->list[str]:
        if not isinstance(available_ids,list) or not isinstance(public_ids,list): raise ValueError("Invalid notebook identifiers")
        self._principal_user(ctx,principal)
        if any(not isinstance(value,str) or not _NOTEBOOK_ID.fullmatch(value) for value in available_ids+public_ids): raise ValueError("Invalid notebook identifiers")
        return list(dict.fromkeys(notebook_id for notebook_id in available_ids if self.notebook_permissions(ctx,principal,notebook_id)))
    def notebook_permissions(self,ctx:RequestContext,principal:AuthPrincipal,notebook_id:str)->list[str]:
        user=self._principal_user(ctx,principal); notebook=self._notebook(ctx,notebook_id)
        if notebook is None: return []
        if notebook.get("owner_user_id")==user["id"]: return ["read","query","import_document","write","manage_members","manage_notebook"]
        snapshot=self._data.membership_snapshot(ctx,notebook_id)
        role=next((m.get("role") for m in snapshot.get("members",[]) if m.get("user_id")==user["id"]),None)
        if role=="editor": return ["read","query","import_document","write"]
        if role=="viewer": return ["read","query"]
        return []
    def authorize_notebook(self,ctx:RequestContext,principal:AuthPrincipal,notebook_id:str,permission:str)->None:
        if not isinstance(permission,str) or permission not in {"read","query","import_document","write","manage_members","manage_notebook"}: raise ValueError("Unknown notebook permission")
        if permission not in self.notebook_permissions(ctx,principal,notebook_id): raise PermissionError("Notebook permission denied")
    def _require_owner(self,ctx,principal,notebook_id):
        user=self._principal_user(ctx,principal); notebook=self._notebook(ctx,notebook_id)
        if notebook is None: raise ValueError("Notebook does not exist")
        if notebook.get("owner_user_id")!=user["id"]: raise PermissionError("Notebook permission denied")
        return user,notebook
    def list_members(self,ctx:RequestContext,principal:AuthPrincipal,notebook_id:str)->list[dict]:
        self._require_owner(ctx,principal,notebook_id); snapshot=self._data.membership_snapshot(ctx,notebook_id)
        return [{"user_id":m["user_id"],"role":m["role"]} for m in snapshot.get("members",[])]
    def list_share_targets(self,ctx:RequestContext,principal:AuthPrincipal,notebook_id:str)->list[dict]:
        _,notebook=self._require_owner(ctx,principal,notebook_id); owner=notebook["owner_user_id"]
        return [{"id":u["id"],"username":u["username"],"is_admin":bool(u.get("is_admin")),"is_guest":bool(u.get("is_guest"))}
                for u in self._data.list_users(ctx) if u.get("is_active") is True and u.get("id")!=owner]
    def set_member(self,ctx:RequestContext,principal:AuthPrincipal,notebook_id:str,user_id:str,role:str)->None:
        self._require_owner(ctx,principal,notebook_id)
        if role not in {"editor","viewer"}: raise ValueError("Invalid notebook role")
        if user_id==self._data.get_notebook(ctx,notebook_id).get("owner_user_id"): raise ValueError("Owner is not a notebook member")
        target=self._data.get_user(ctx,user_id)
        if not isinstance(target,dict) or target.get("is_active") is not True or (target.get("is_guest") and role!="viewer"): raise ValueError("User unavailable")
        with self._lock: self._data.put_member(ctx,notebook_id,user_id,role)
    def remove_member(self,ctx:RequestContext,principal:AuthPrincipal,notebook_id:str,user_id:str)->None:
        self._require_owner(ctx,principal,notebook_id)
        if not isinstance(user_id,str) or not user_id: raise ValueError("Invalid user identifier")
        with self._lock: self._data.delete_member(ctx,notebook_id,user_id)
    def list_admin_users(self,ctx:RequestContext,principal:AuthPrincipal)->list[dict]:
        if not self._principal_user(ctx,principal).get("is_admin"): raise PermissionError("Permission denied")
        return [_public_user(u) for u in self._data.list_users(ctx,active_only=False) if not u.get("is_guest")]
    def set_user_active(self,ctx:RequestContext,principal:AuthPrincipal,user_id:str,active:bool)->None:
        if not self._principal_user(ctx,principal).get("is_admin"): raise PermissionError("Permission denied")
        if type(active) is not bool: raise ValueError("Invalid active state")
        target=self._data.get_user(ctx,user_id)
        if not isinstance(target,dict) or target.get("is_guest"): raise ValueError("User unavailable")
        if not active and target.get("is_admin") and target.get("is_active"):
            admins=[u for u in self._data.list_users(ctx) if u.get("is_admin") and u.get("is_active") is True]
            if len(admins)<=1: raise PermissionError("Cannot deactivate the last administrator")
        self._data.set_user_active(ctx,user_id,active)
    def _quota_date(self):
        now=datetime.now(timezone(timedelta(hours=8)))
        reset=(now+timedelta(days=1)).replace(hour=0,minute=0,second=0,microsecond=0)
        return now.date().isoformat(),reset.isoformat()
    def quota_status(self,ctx:RequestContext)->dict:
        date,reset=self._quota_date(); used=self._data.site_quota_used(ctx,date)
        if type(used) is not int or used<0: raise ValueError("Invalid site quota")
        return {"scope":"site","limit":self._daily_limit,"used":used,"remaining":max(0,self._daily_limit-used),"reset_at":reset}
    def reserve_query(self,ctx:RequestContext)->dict:
        date,reset=self._quota_date(); used=self._data.reserve_site_quota(ctx,date,self._daily_limit)
        if used is None: raise PermissionError("Daily query quota exhausted")
        if type(used) is not int or not 1<=used<=self._daily_limit: raise ValueError("Invalid site quota")
        return {"scope":"site","limit":self._daily_limit,"used":used,"remaining":max(0,self._daily_limit-used),"reset_at":reset}
__all__=["AuthService"]
