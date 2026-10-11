# cython: annotation_typing=False
# cython: infer_types=False
from __future__ import annotations

import re
import threading
from datetime import datetime, timedelta, timezone

from auth_runtime import AuthRuntime
from core_specifications import AuthPrincipal, RequestContext, StateStorePort, NotebookStorePort

__version__ = "0.4.0"

_READ_PERMISSIONS = frozenset({"read", "query"})
_WRITE_PERMISSIONS = frozenset({"create_notebook", "import_document", "write", "archive_notebook", "restore_notebook"})
_ROLE_PERMISSIONS = {
    "viewer": ["read", "query"],
    "editor": ["read", "query", "import_document", "write"],
    "manager": ["read", "query", "import_document", "write", "manage_members", "manage_notebook"],
}
_NOTEBOOK_ID = re.compile(r"\w[\w.-]*", re.UNICODE)


class AuthService:
    """Authentication business facade over the low-level proof verifier."""

    def __init__(self, proxy_token: str = "", owner_id: str = "", store: NotebookStorePort | None = None) -> None:
        self._runtime = AuthRuntime(proxy_token, owner_id)
        self._owner_id = owner_id
        self._store = store
        self._lock = threading.RLock()
        if store is not None:
            store.configure_roles(RequestContext("auth-boot", "auth-boot"), _ROLE_PERMISSIONS)

    def guest(self, ctx: RequestContext) -> AuthPrincipal:
        return self._runtime.guest(ctx)

    def authenticate_proxy(
        self, ctx: RequestContext, proxy_token: str, user_id: str, role: str
    ) -> AuthPrincipal:
        principal = self._runtime.authenticate_proxy(ctx, proxy_token, user_id, role)
        if self._store is not None:
            self._store.register_user(ctx, principal.user_id)
        return principal

    def authorize(
        self, ctx: RequestContext, principal: AuthPrincipal, permission: str
    ) -> None:
        if not isinstance(permission, str) or permission not in _READ_PERMISSIONS | _WRITE_PERMISSIONS | {"authenticated"}:
            raise ValueError("Unknown permission")
        administrator = self._runtime.is_administrator(ctx, principal)
        if permission == "authenticated" and not self._runtime.is_authenticated(ctx, principal):
            raise PermissionError("Authentication required")
        if permission in _WRITE_PERMISSIONS and not administrator:
            raise PermissionError("Permission denied")

    def allowed_notebooks(
        self,
        ctx: RequestContext,
        principal: AuthPrincipal,
        available_ids: list[str],
        public_ids: list[str],
    ) -> list[str]:
        administrator = self._runtime.is_administrator(ctx, principal)
        self._validate_ids(available_ids)
        self._validate_ids(public_ids)
        published = set(public_ids)
        return list(dict.fromkeys(
            notebook_id for notebook_id in available_ids
            if self.notebook_permissions(ctx, principal, notebook_id, notebook_id in published)
        ))

    def _snapshot(self, ctx: RequestContext, notebook_id: str) -> dict:
        self._validate_ids([notebook_id])
        if self._store is None:
            return {"revision": 0, "members": [], "is_public": False, "archived": False}
        return self._store.membership_snapshot(ctx, notebook_id)

    def _snapshot_permissions(self, ctx: RequestContext, principal: AuthPrincipal, snapshot: dict, public: bool = False) -> list[str]:
        admin = self._runtime.is_administrator(ctx, principal)
        if snapshot.get("archived"):
            return []
        if public or snapshot.get("is_public"):
            return ["read", "query"]
        if admin:
            return [*_ROLE_PERMISSIONS["manager"], "archive_notebook", "restore_notebook"]
        if not self._runtime.is_authenticated(ctx, principal) or self._store is None:
            return []
        role = next((m["role"] for m in snapshot["members"] if m["user_id"] == principal.user_id), None)
        if role not in _ROLE_PERMISSIONS:
            return []
        granted = set(self._store.role_permissions(ctx, role))
        return [p for p in _ROLE_PERMISSIONS[role] if p in granted]

    @staticmethod
    def _valid_user(user_id: object) -> bool:
        return isinstance(user_id, str) and 0 < len(user_id) <= 128 and user_id == user_id.strip() and all(
            ch.isalnum() or ch in "@_.-" for ch in user_id
        )

    def notebook_permissions(self, ctx: RequestContext, principal: AuthPrincipal, notebook_id: str, public: bool = False) -> list[str]:
        self._validate_ids([notebook_id])
        # Verify even before testing existence, so forged principals always fail.
        self._runtime.is_administrator(ctx, principal)
        try:
            snapshot = self._snapshot(ctx, notebook_id)
        except ValueError:
            return []
        if self._store is not None:
            public = bool(snapshot.get("is_public"))
        return self._snapshot_permissions(ctx, principal, snapshot, public)

    def authorize_notebook(self, ctx: RequestContext, principal: AuthPrincipal, notebook_id: str, permission: str, public: bool = False) -> None:
        if not isinstance(permission, str) or permission not in _ROLE_PERMISSIONS["manager"] + ["archive_notebook", "restore_notebook"]:
            raise ValueError("Unknown notebook permission")
        if permission not in self.notebook_permissions(ctx, principal, notebook_id, public):
            raise PermissionError("Notebook permission denied")

    def list_members(self, ctx: RequestContext, principal: AuthPrincipal, notebook_id: str) -> list[dict]:
        with self._lock:
            snapshot = self._snapshot(ctx, notebook_id)
            if "manage_members" not in self._snapshot_permissions(ctx, principal, snapshot):
                raise PermissionError("Notebook permission denied")
            return [dict(member) for member in snapshot["members"]]

    def _change_member(self, ctx, principal, notebook_id, user_id, role):
        self._runtime.is_administrator(ctx, principal)
        if not self._valid_user(user_id) or user_id == self._owner_id or (role is not None and (not isinstance(role,str) or role not in _ROLE_PERMISSIONS)):
            raise ValueError("Invalid notebook member")
        if self._store is None:
            raise PermissionError("Notebook policy store unavailable")
        with self._lock:
            for _ in range(64):
                snapshot = self._snapshot(ctx, notebook_id)
                if "manage_members" not in self._snapshot_permissions(ctx, principal, snapshot):
                    raise PermissionError("Notebook permission denied")
                if role is None:
                    done = self._store.delete_member(ctx,notebook_id,user_id,snapshot["revision"])
                else:
                    done = self._store.put_member(ctx,notebook_id,user_id,role,snapshot["revision"])
                if done: return
            raise PermissionError("Notebook policy changed; retry request")

    def set_member(self, ctx: RequestContext, principal: AuthPrincipal, notebook_id: str, user_id: str, role: str) -> None:
        if not isinstance(role,str) or role not in _ROLE_PERMISSIONS:
            raise ValueError("Invalid notebook role")
        self._change_member(ctx,principal,notebook_id,user_id,role)

    def remove_member(self, ctx: RequestContext, principal: AuthPrincipal, notebook_id: str, user_id: str) -> None:
        self._change_member(ctx,principal,notebook_id,user_id,None)

    @staticmethod
    def _validate_ids(values: object) -> None:
        if not isinstance(values, list) or any(
            not isinstance(value, str) or _NOTEBOOK_ID.fullmatch(value) is None
            for value in values
        ):
            raise ValueError("Invalid notebook identifiers")


class DailyQueryQuota:
    """Site-wide query policy backed by an injected atomic state-store port."""

    def __init__(self, store: StateStorePort, limit: int = 20) -> None:
        if type(limit) is not int or limit < 1:
            raise ValueError("daily query limit must be a positive integer")
        self._store = store
        self._limit = limit

    def _identity(self, ctx: RequestContext):
        now = datetime.now(timezone(timedelta(hours=8)))
        reset = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        # Client-supplied identities, sessions and roles never partition the budget.
        fixed = RequestContext(ctx.trace_id, ctx.request_id, "__rag_shared_web_quota__")
        return fixed, "web-query:" + now.date().isoformat(), reset.isoformat()

    def _result(self, used: int, reset: str) -> dict:
        return {"scope": "site", "limit": self._limit, "used": used,
                "remaining": max(0, self._limit - used), "reset_at": reset}

    def status(self, ctx: RequestContext) -> dict:
        fixed, key, reset = self._identity(ctx)
        used = self._store.get(fixed, key)
        used = 0 if used is None else used
        if type(used) is not int or used < 0:
            raise ValueError("invalid daily query counter")
        return self._result(used, reset)

    def reserve(self, ctx: RequestContext) -> dict:
        fixed, key, reset = self._identity(ctx)
        used = self._store.increment_if_below(fixed, key, self._limit)
        if used is None:
            raise PermissionError("Daily query quota exhausted")
        return self._result(used, reset)


__all__ = ["AuthService", "DailyQueryQuota"]
