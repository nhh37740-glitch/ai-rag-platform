# cython: annotation_typing=False
# cython: infer_types=False
from __future__ import annotations

import re
import threading
from datetime import datetime, timedelta, timezone

from auth_runtime import AuthRuntime
from core_specifications import AuthPrincipal, RequestContext, StateStorePort

__version__ = "0.3.0"

_READ_PERMISSIONS = frozenset({"read", "query"})
_WRITE_PERMISSIONS = frozenset({"create_notebook", "import_document", "write"})
_ROLE_PERMISSIONS = {
    "viewer": ["read", "query"],
    "editor": ["read", "query", "import_document", "write"],
    "manager": ["read", "query", "import_document", "write", "manage_members"],
}
_NOTEBOOK_ID = re.compile(r"\w[\w.-]*", re.UNICODE)


class AuthService:
    """Authentication business facade over the low-level proof verifier."""

    def __init__(self, proxy_token: str = "", owner_id: str = "", store: StateStorePort | None = None) -> None:
        self._runtime = AuthRuntime(proxy_token, owner_id)
        self._owner_id = owner_id
        self._store = store
        self._lock = threading.RLock()

    def guest(self, ctx: RequestContext) -> AuthPrincipal:
        return self._runtime.guest(ctx)

    def authenticate_proxy(
        self, ctx: RequestContext, proxy_token: str, user_id: str, role: str
    ) -> AuthPrincipal:
        return self._runtime.authenticate_proxy(ctx, proxy_token, user_id, role)

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
            if administrator or self.notebook_permissions(ctx, principal, notebook_id, notebook_id in published)
        ))

    def _acl_context(self, ctx: RequestContext) -> RequestContext:
        return RequestContext(ctx.trace_id, ctx.request_id, "__rag_notebook_acl__")

    def _members(self, ctx: RequestContext, notebook_id: str) -> dict:
        self._validate_ids([notebook_id])
        if self._store is None:
            return {}
        value = self._store.get(self._acl_context(ctx), "notebook-members:" + notebook_id)
        if value is None:
            return {}
        if not isinstance(value, dict) or any(
            not self._valid_user(user_id) or not isinstance(role, str) or role not in _ROLE_PERMISSIONS
            for user_id, role in value.items()
        ):
            raise PermissionError("Invalid notebook policy")
        return dict(value)

    @staticmethod
    def _valid_user(user_id: object) -> bool:
        return isinstance(user_id, str) and 0 < len(user_id) <= 128 and user_id == user_id.strip() and all(
            ch.isalnum() or ch in "@_.-" for ch in user_id
        )

    def notebook_permissions(self, ctx: RequestContext, principal: AuthPrincipal, notebook_id: str, public: bool = False) -> list[str]:
        self._validate_ids([notebook_id])
        admin = self._runtime.is_administrator(ctx, principal)
        if public:
            return ["read", "query"]
        if admin:
            return list(_ROLE_PERMISSIONS["manager"])
        if not self._runtime.is_authenticated(ctx, principal):
            return []
        role = self._members(ctx, notebook_id).get(principal.user_id)
        return list(_ROLE_PERMISSIONS.get(role, []))

    def authorize_notebook(self, ctx: RequestContext, principal: AuthPrincipal, notebook_id: str, permission: str, public: bool = False) -> None:
        if not isinstance(permission, str) or permission not in _ROLE_PERMISSIONS["manager"]:
            raise ValueError("Unknown notebook permission")
        if permission not in self.notebook_permissions(ctx, principal, notebook_id, public):
            raise PermissionError("Notebook permission denied")

    def list_members(self, ctx: RequestContext, principal: AuthPrincipal, notebook_id: str) -> list[dict]:
        with self._lock:
            self.authorize_notebook(ctx, principal, notebook_id, "manage_members")
            return [{"user_id": user_id, "role": role} for user_id, role in sorted(self._members(ctx, notebook_id).items())]

    def set_member(self, ctx: RequestContext, principal: AuthPrincipal, notebook_id: str, user_id: str, role: str) -> None:
        with self._lock:
            self.authorize_notebook(ctx, principal, notebook_id, "manage_members")
            if not self._valid_user(user_id) or user_id == self._owner_id or not isinstance(role, str) or role not in _ROLE_PERMISSIONS:
                raise ValueError("Invalid notebook member")
            if self._store is None:
                raise PermissionError("Notebook policy store unavailable")
            members = self._members(ctx, notebook_id)
            members[user_id] = role
            self._store.set(self._acl_context(ctx), "notebook-members:" + notebook_id, members)

    def remove_member(self, ctx: RequestContext, principal: AuthPrincipal, notebook_id: str, user_id: str) -> None:
        with self._lock:
            self.authorize_notebook(ctx, principal, notebook_id, "manage_members")
            if not self._valid_user(user_id) or user_id == self._owner_id:
                raise ValueError("Invalid notebook member")
            if self._store is None:
                raise PermissionError("Notebook policy store unavailable")
            members = self._members(ctx, notebook_id)
            members.pop(user_id, None)
            self._store.set(self._acl_context(ctx), "notebook-members:" + notebook_id, members)

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
