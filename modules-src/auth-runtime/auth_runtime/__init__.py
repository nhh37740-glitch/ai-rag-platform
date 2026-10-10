# cython: annotation_typing=False
# cython: infer_types=False
from __future__ import annotations

import hashlib
import hmac
import secrets

from core_specifications import AuthPrincipal, RequestContext

__version__ = "0.3.0"

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

    def is_administrator(self, ctx: RequestContext, principal: AuthPrincipal) -> bool:
        """Validate a principal and return its cryptographically verified role."""
        return self._validate_principal(principal)


__all__ = ["AuthRuntime"]
