# cython: annotation_typing=False
# cython: infer_types=False
from __future__ import annotations

import hashlib
import hmac
import secrets

from core_specifications import AuthPrincipal, RequestContext

__version__ = "0.4.0"

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


class AuthRuntime:
    """Low-level guest identity and proxy-proof verification primitives."""

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
        return f"AuthRuntime(mode={mode!r})"

    def _identity_proof(self, user_id: str, role: str) -> str:
        payload = b"auth-runtime:identity:v2\0"
        for value in (user_id, role):
            encoded = value.encode("utf-8")
            payload += str(len(encoded)).encode("ascii") + b":" + encoded
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
        valid_role = (role == "admin" and user_id == self._owner_id) or (
            role == "user" and user_id != self._owner_id
        )
        if not (self._configured and proof_matches and _identity_valid(user_id) and valid_role):
            raise PermissionError("Authentication denied")
        return AuthPrincipal(user_id=user_id, role=role, proof=self._identity_proof(user_id, role))

    def _validate_principal(self, principal: AuthPrincipal) -> bool:
        if type(principal) is not AuthPrincipal or not _identity_valid(principal.user_id):
            raise PermissionError("Invalid authentication principal")
        if principal.role == "guest" and principal.proof == "":
            return False
        valid_role = (principal.role == "admin" and principal.user_id == self._owner_id) or (
            principal.role == "user" and principal.user_id != self._owner_id
        )
        if self._configured and valid_role and hmac.compare_digest(
            self._identity_proof(principal.user_id, principal.role).encode("ascii"),
            _credential_bytes(principal.proof),
        ):
            return True
        raise PermissionError("Invalid authentication principal")

    def is_authenticated(self, ctx: RequestContext, principal: AuthPrincipal) -> bool:
        return self._validate_principal(principal)

    def is_administrator(self, ctx: RequestContext, principal: AuthPrincipal) -> bool:
        """Validate a principal and return its cryptographically verified role."""
        return self._validate_principal(principal) and principal.role == "admin"


__all__ = ["AuthRuntime"]
