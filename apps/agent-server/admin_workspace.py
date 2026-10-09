"""Private HTTP boundary for an owner identity verified by the login gateway."""
from __future__ import annotations

import hmac
from urllib.parse import urlsplit

from fastapi.responses import JSONResponse


class AdminWorkspaceBoundary:
    """Validate server proof and owner identity before parsing a private request."""

    def __init__(self, app, *, proxy_token: str, owner_id: str, origin: str):
        parsed = urlsplit(origin)
        if (
            len(proxy_token.encode("utf-8")) < 32
            or not owner_id.strip() or owner_id != owner_id.strip()
            or parsed.scheme != "https" or not parsed.hostname
            or parsed.username or parsed.password or parsed.path
            or parsed.query or parsed.fragment
        ):
            raise RuntimeError("管理员代理缺少有效的认证证明、拥有者或 HTTPS Origin 配置")
        self.app = app
        self.proxy_token = proxy_token.encode("utf-8")
        self.owner_id = owner_id
        self.origin = origin

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            await self.app(scope, receive, send)
            return
        if scope["type"] != "http":
            await send({"type": "websocket.close", "code": 1008})
            return

        # The health endpoint contains only metadata from the bundled corpus.
        if scope["method"] == "GET" and scope["path"] == "/api/demo":
            await self.app(scope, receive, send)
            return

        headers: dict[bytes, list[bytes]] = {}
        for key, value in scope.get("headers", []):
            headers.setdefault(key.lower(), []).append(value)

        def single(name: bytes) -> bytes:
            values = headers.get(name, [])
            return values[0] if len(values) == 1 else b""

        proof = single(b"x-rag-proxy-token")
        verified = (
            hmac.compare_digest(proof, self.proxy_token)
            and single(b"x-rag-user-id") == self.owner_id.encode("utf-8")
            and single(b"x-rag-role") == b"admin"
        )
        write = scope["method"] not in {"GET", "HEAD", "OPTIONS"}
        write = write or scope["path"] == "/api/chat/stream"
        same_origin = (
            single(b"origin") == self.origin.encode("utf-8")
            and single(b"sec-fetch-site") in {b"", b"same-origin"}
        )
        if not verified or (write and not same_origin):
            response = JSONResponse(
                {"detail": "仅允许已登录的拥有者管理员访问知识工作区"},
                status_code=403, headers={"Cache-Control": "no-store"},
            )
            await response(scope, receive, send)
            return

        scope.setdefault("state", {})["admin_owner_id"] = self.owner_id

        async def private_send(message):
            if message["type"] == "http.response.start":
                message["headers"] = [
                    (key, value) for key, value in message.get("headers", [])
                    if key.lower() != b"cache-control"
                ] + [(b"cache-control", b"no-store")]
            await send(message)

        await self.app(scope, receive, private_send)
