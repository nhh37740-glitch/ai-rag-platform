# cython: annotation_typing=False
# cython: infer_types=False
from __future__ import annotations

import hashlib
import hmac
import re
import secrets

from core_specifications import AuthPrincipal, RequestContext

__version__ = "0.1.0"

_READ_PERMISSIONS = frozenset({"read", "query"})
_WRITE_PERMISSIONS = frozenset({"create_notebook", "import_document", "write"})
_NOTEBOOK_ID = re.compile(r"\w[\w.-]*", re.UNICODE)


def _identity_valid(value: object) -> bool:
    return isinstance(value, str) and bool(_credential_bytes(value)) and value == value.strip() and not any(
        ord(character) < 32 or ord(character) == 127 for character in value
    )


def _credential_bytes(value: object) -> bytes:
    if not isinstance(value, str):
        return b""
    try:
        return value.encode("utf-8")
    except UnicodeEncodeError:
        return b""


class AuthService:
    """Server-side permissions with administrator proofs scoped to this instance."""

    def __init__(self, proxy_token: str = "", owner_id: str = "") -> None:
        if not isinstance(proxy_token, str) or not isinstance(owner_id, str):
            raise ValueError("Invalid authentication configuration")
        configured = bool(proxy_token or owner_id)
        token_bytes = _credential_bytes(proxy_token)
        if configured and (
            not proxy_token.strip() or len(token_bytes) < 32 or not _identity_valid(owner_id)
        ):
            raise ValueError("Invalid authentication configuration")
        self._proxy_token = token_bytes
        self._owner_id = owner_id
        self._signing_key = secrets.token_bytes(32)
        self._configured = configured

    def __repr__(self) -> str:
        mode = "proxy" if self._configured else "guest"
        return f"AuthService(mode={mode!r})"

    def _admin_proof(self) -> str:
        # Length-framed identity avoids ambiguous string concatenation. The
        # signing key is generated per service and never included in a principal.
        owner = self._owner_id.encode("utf-8")
        payload = b"auth-runtime:admin:v1\0" + str(len(owner)).encode("ascii") + b":" + owner
        return hmac.new(self._signing_key, payload, hashlib.sha256).hexdigest()

    def guest(self, ctx: RequestContext) -> AuthPrincipal:
        user_id = ctx.user_id or "guest"
        if not _identity_valid(user_id):
            raise ValueError("Invalid guest identity")
        return AuthPrincipal(user_id=user_id, role="guest")

    def authenticate_proxy(
        self,
        ctx: RequestContext,
        proxy_token: str,
        user_id: str,
        role: str,
    ) -> AuthPrincipal:
        # Compare the proxy proof even if other supplied identity fields fail.
        # Invalid UTF-8 input becomes an empty value, never an error containing it.
        proof_matches = hmac.compare_digest(self._proxy_token, _credential_bytes(proxy_token))
        if not (self._configured and proof_matches and user_id == self._owner_id and role == "admin"):
            raise PermissionError("Authentication denied")
        return AuthPrincipal(user_id=self._owner_id, role="admin", proof=self._admin_proof())

    def _validate_principal(self, principal: AuthPrincipal) -> bool:
        """Return whether a validated principal is an administrator."""
        if type(principal) is not AuthPrincipal or not _identity_valid(principal.user_id):
            raise PermissionError("Invalid authentication principal")
        if principal.role == "guest" and principal.proof == "":
            return False
        if principal.role == "admin":
            proof_matches = hmac.compare_digest(
                self._admin_proof().encode("ascii"), _credential_bytes(principal.proof)
            )
            if self._configured and principal.user_id == self._owner_id and proof_matches:
                return True
        raise PermissionError("Invalid authentication principal")

    def authorize(self, ctx: RequestContext, principal: AuthPrincipal, permission: str) -> None:
        if not isinstance(permission, str) or permission not in _READ_PERMISSIONS | _WRITE_PERMISSIONS:
            raise ValueError("Unknown permission")
        administrator = self._validate_principal(principal)
        if permission in _WRITE_PERMISSIONS and not administrator:
            raise PermissionError("Permission denied")

    @staticmethod
    def _validate_ids(values: object) -> None:
        if not isinstance(values, list) or any(
            not isinstance(value, str) or _NOTEBOOK_ID.fullmatch(value) is None
            for value in values
        ):
            raise ValueError("Invalid notebook identifiers")

    def allowed_notebooks(
        self,
        ctx: RequestContext,
        principal: AuthPrincipal,
        available_ids: list[str],
        public_ids: list[str],
    ) -> list[str]:
        administrator = self._validate_principal(principal)
        self._validate_ids(available_ids)
        self._validate_ids(public_ids)
        published = set(public_ids)
        return list(dict.fromkeys(
            notebook_id for notebook_id in available_ids
            if administrator or notebook_id in published
        ))


__all__ = ["AuthService"]
