# cython: annotation_typing=False
# cython: infer_types=False
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from auth_runtime import AuthRuntime
from core_specifications import AuthPrincipal, RequestContext, StateStorePort

__version__ = "0.2.0"

_READ_PERMISSIONS = frozenset({"read", "query"})
_WRITE_PERMISSIONS = frozenset({"create_notebook", "import_document", "write"})
_NOTEBOOK_ID = re.compile(r"\w[\w.-]*", re.UNICODE)


class AuthService:
    """Authentication business facade over the low-level proof verifier."""

    def __init__(self, proxy_token: str = "", owner_id: str = "") -> None:
        self._runtime = AuthRuntime(proxy_token, owner_id)

    def guest(self, ctx: RequestContext) -> AuthPrincipal:
        return self._runtime.guest(ctx)

    def authenticate_proxy(
        self, ctx: RequestContext, proxy_token: str, user_id: str, role: str
    ) -> AuthPrincipal:
        return self._runtime.authenticate_proxy(ctx, proxy_token, user_id, role)

    def authorize(
        self, ctx: RequestContext, principal: AuthPrincipal, permission: str
    ) -> None:
        if not isinstance(permission, str) or permission not in _READ_PERMISSIONS | _WRITE_PERMISSIONS:
            raise ValueError("Unknown permission")
        administrator = self._runtime.is_administrator(ctx, principal)
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
            if administrator or notebook_id in published
        ))

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
