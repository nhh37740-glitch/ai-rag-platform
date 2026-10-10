"""HTTP identity adapter for the owner verified by the login gateway."""
from __future__ import annotations

import uuid
from urllib.parse import urlsplit

from auth_runtime import AuthService
from core_specifications import RequestContext
from fastapi.responses import JSONResponse


PUBLIC_KB_ID = "cmrc2018-demo"


def public_read_path(path: str) -> bool:
    """Public reads never include private notebooks, uploads or private traces."""
    if path in {"/api/demo", "/api/auth/session", "/api/notebooks"}:
        return True
    if path in {
        f"/api/notebooks/{PUBLIC_KB_ID}/documents",
        f"/api/notebooks/{PUBLIC_KB_ID}/suggestions",
    }:
        return True
    return path.startswith("/api/demo/documents/") and len(path.split("/")) == 5


class AdminWorkspaceBoundary:
    """Validate server proof with the shared AuthService before parsing a body."""

    def __init__(self, app, *, proxy_token: str, owner_id: str, origin: str, auth_service=None):
        try:
            parsed = urlsplit(origin)
            if (
                parsed.scheme != "https" or not parsed.hostname
                or parsed.username or parsed.password or parsed.path
                or parsed.query or parsed.fragment
            ):
                raise ValueError("invalid origin")
            # Standalone boundary tests may construct their own service. The server
            # injects its exact instance so issued principals remain valid there.
            configured = AuthService(proxy_token, owner_id)
        except ValueError:
            raise RuntimeError("管理员代理缺少有效的认证证明、拥有者或 HTTPS Origin 配置") from None
        if not proxy_token or not owner_id:
            raise RuntimeError("管理员代理缺少有效的认证证明、拥有者或 HTTPS Origin 配置")
        self.app = app
        self.auth_service = auth_service if auth_service is not None else configured
        self.owner_id = owner_id
        self.origin = origin

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            await self.app(scope, receive, send)
            return
        if scope["type"] != "http":
            await send({"type": "websocket.close", "code": 1008})
            return

        headers: dict[bytes, list[bytes]] = {}
        for key, value in scope.get("headers", []):
            headers.setdefault(key.lower(), []).append(value)

        def single(name: bytes) -> str:
            values = headers.get(name, [])
            if len(values) != 1:
                return ""
            try:
                return values[0].decode("utf-8")
            except UnicodeError:
                return ""

        request_id = uuid.uuid4().hex
        ctx = RequestContext(request_id, request_id, "guest")
        supplied_identity = any(
            name in headers for name in (b"x-rag-proxy-token", b"x-rag-user-id", b"x-rag-role")
        )
        anonymous_public = scope["method"] == "GET" and public_read_path(scope["path"])
        write = scope["method"] not in {"GET", "HEAD", "OPTIONS"} or scope["path"] == "/api/chat/stream"
        same_origin = single(b"origin") == self.origin and single(b"sec-fetch-site") in {"", "same-origin"}
        try:
            if supplied_identity:
                principal = self.auth_service.authenticate_proxy(
                    ctx, single(b"x-rag-proxy-token"), single(b"x-rag-user-id"), single(b"x-rag-role")
                )
            else:
                principal = self.auth_service.guest(ctx)
            permission = "read"
            if not anonymous_public:
                # The private UI, traces, progress and notebook data are admin-only.
                permission = "write"
            if scope["method"] == "POST" and scope["path"] == "/api/notebooks":
                permission = "create_notebook"
            elif scope["method"] == "POST" and scope["path"].endswith("/files"):
                permission = "import_document"
            self.auth_service.authorize(ctx, principal, permission)
            if write and not same_origin:
                raise PermissionError("Origin denied")
        except (PermissionError, ValueError):
            response = JSONResponse(
                {"detail": "仅允许已登录的拥有者管理员访问知识工作区"},
                status_code=403, headers={"Cache-Control": "no-store"},
            )
            await response(scope, receive, send)
            return

        state = scope.setdefault("state", {})
        state["auth_principal"] = principal
        state["auth_context"] = RequestContext(ctx.trace_id, ctx.request_id, principal.user_id)
        if principal.role == "admin":
            state["admin_owner_id"] = principal.user_id

        async def private_send(message):
            if message["type"] == "http.response.start":
                message["headers"] = [
                    (key, value) for key, value in message.get("headers", [])
                    if key.lower() != b"cache-control"
                ] + [(b"cache-control", b"no-store")]
            await send(message)

        await self.app(scope, receive, private_send)
