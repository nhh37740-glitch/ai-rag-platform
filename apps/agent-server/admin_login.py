"""Isolated login adapter for the existing Media owner's session account.

Run this app separately from the private RAG app; it has no data volumes.
"""
from __future__ import annotations

import hmac
import json
import os
import time
from collections import deque
from dataclasses import dataclass
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

COOKIE = "rag_admin_session"
PREFIX = "/projects/apps/rag/admin/"
CSRF_HEADER = "X-CSRF-TOKEN"


@dataclass(frozen=True)
class LoginConfig:
    proxy_token: str
    owner_id: str
    origin: str
    auth_base: str
    owner_username: str = "owner"

    def __post_init__(self):
        origin, backend = urlsplit(self.origin), urlsplit(self.auth_base)
        if (
            len(self.proxy_token.encode()) < 32 or not self.owner_id.strip()
            or self.owner_id != self.owner_id.strip() or self.owner_username != "owner"
            or origin.scheme != "https" or not origin.hostname or origin.path
            or origin.username or origin.password or origin.query or origin.fragment
            or backend.scheme != "http"
            or backend.hostname not in {"host.docker.internal", "127.0.0.1", "localhost"}
            or backend.path != "/api/v1/auth" or backend.username or backend.password
            or backend.query or backend.fragment
        ):
            raise RuntimeError("管理员登录需要指定拥有者、HTTPS Origin、内部 Media 地址和服务器认证证明")

    @classmethod
    def from_env(cls):
        return cls(
            proxy_token=os.environ.get("RAG_ADMIN_PROXY_TOKEN", ""),
            owner_id=os.environ.get("RAG_ADMIN_OWNER_ID", ""),
            origin=os.environ.get("RAG_ADMIN_ORIGIN", ""),
            auth_base=os.environ.get("RAG_ADMIN_AUTH_BASE", "http://host.docker.internal:8088/api/v1/auth"),
        )


def create_app(config: LoginConfig, *, transport=None):
    app = FastAPI(title="Owner login adapter", docs_url=None, redoc_url=None, openapi_url=None)
    attempts: deque[float] = deque(maxlen=10)

    def error(message: str, status: int):
        return JSONResponse({"detail": message}, status_code=status, headers={"Cache-Control": "no-store"})

    def same_origin(req: Request):
        return req.headers.get("origin") == config.origin and req.headers.get("sec-fetch-site", "") in {"", "same-origin"}

    def session(req: Request):
        # Reject repeated session cookies rather than choosing one ambiguously.
        values = []
        for raw in req.headers.getlist("cookie"):
            for item in raw.split(";"):
                name, separator, value = item.strip().partition("=")
                if separator and name == COOKIE:
                    values.append(value)
        if len(values) != 1 or not values[0] or len(values[0]) > 512:
            return ""
        value = values[0]
        if any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789+/=_-" for character in value):
            return ""
        return value

    async def upstream(req: Request, method: str, endpoint: str, *, body=None, csrf=""):
        headers = {"Accept": "application/json"}
        value = session(req)
        if value:
            headers["Cookie"] = "SESSION=" + value
        if csrf:
            headers[CSRF_HEADER] = csrf
        # A separate cookie jar per request prevents identities crossing requests.
        async with httpx.AsyncClient(transport=transport, timeout=5, follow_redirects=False, trust_env=False) as client:
            return await client.request(method, config.auth_base + endpoint, json=body, headers=headers)

    def copy_session(response: JSONResponse, remote: httpx.Response):
        for raw in remote.headers.get_list("set-cookie"):
            cookies = SimpleCookie()
            try:
                cookies.load(raw)
            except Exception:
                continue
            if "SESSION" in cookies:
                value = cookies["SESSION"].value
                if value and len(value) <= 512:
                    response.set_cookie(COOKIE, value, secure=True, httponly=True, samesite="strict", path=PREFIX)

    def is_owner(value):
        return isinstance(value, dict) and value.get("userId") == config.owner_id and value.get("username") == config.owner_username

    async def identity(req: Request):
        if not session(req):
            return None
        remote = await upstream(req, "GET", "/me")
        if remote.status_code != 200:
            return None
        return remote.json()

    @app.middleware("http")
    async def secure_responses(req: Request, call_next):
        try:
            response = await call_next(req)
        except (httpx.HTTPError, ValueError, KeyError):
            response = error("登录服务暂时不可用，请稍后重试。", 503)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
        return response

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/")
    def page():
        return FileResponse(Path(__file__).parent / "webui" / "admin_login.html")

    @app.get("/login.js")
    def script():
        return FileResponse(Path(__file__).parent / "webui" / "admin_login.js", media_type="text/javascript")

    @app.get("/login.css")
    def style():
        return FileResponse(Path(__file__).parent / "webui" / "admin_login.css", media_type="text/css")

    @app.get("/csrf")
    async def csrf(req: Request):
        remote = await upstream(req, "GET", "/csrf")
        value = remote.json() if remote.status_code == 200 else None
        if not isinstance(value, dict) or value.get("headerName") != CSRF_HEADER or not isinstance(value.get("token"), str) or not 0 < len(value["token"]) <= 512:
            return error("登录服务暂时不可用，请稍后重试。", 503)
        response = JSONResponse({"token": value["token"], "headerName": CSRF_HEADER})
        copy_session(response, remote)
        return response

    @app.post("/login")
    async def login(req: Request):
        if not same_origin(req):
            return error("请从本站 HTTPS 登录页面提交。", 403)
        now = time.monotonic()
        while attempts and now - attempts[0] >= 300:
            attempts.popleft()
        if len(attempts) >= 10:
            return error("登录尝试过于频繁，请五分钟后再试。", 429)
        attempts.append(now)
        content = bytearray()
        async for part in req.stream():
            content.extend(part)
            if len(content) > 4096:
                return error("登录请求无效。", 422)
        try:
            body = json.loads(content)
        except (ValueError, UnicodeDecodeError):
            return error("登录请求无效。", 422)
        if (
            not isinstance(body, dict) or set(body) != {"username", "password"}
            or not isinstance(body["username"], str) or not 0 < len(body["username"]) <= 64
            or not isinstance(body["password"], str) or not 0 < len(body["password"]) <= 200
        ):
            return error("登录请求无效。", 422)
        token = req.headers.get(CSRF_HEADER, "")
        if not token or len(token) > 512 or not session(req):
            return error("登录页面已过期，请刷新后重试。", 403)
        remote = await upstream(req, "POST", "/login", body=body, csrf=token)
        if remote.status_code != 200:
            return error("账号或密码不正确，或登录页面已过期。", 401)
        if not is_owner(remote.json()):
            response = error("该账号没有知识工作区的管理权限。", 403)
            response.delete_cookie(COOKIE, path=PREFIX, secure=True, httponly=True, samesite="strict")
            return response
        response = JSONResponse({"administrator": True, "redirect": PREFIX})
        copy_session(response, remote)
        return response

    @app.post("/logout")
    async def logout(req: Request):
        if not same_origin(req) or not session(req) or not req.headers.get(CSRF_HEADER):
            return error("退出登录请求无效。", 403)
        remote = await upstream(req, "POST", "/logout", csrf=req.headers[CSRF_HEADER])
        if remote.status_code not in {200, 204}:
            return error("退出登录失败，请刷新后重试。", 503)
        response = JSONResponse({"logged_out": True})
        response.delete_cookie(COOKIE, path=PREFIX, secure=True, httponly=True, samesite="strict")
        return response

    @app.get("/verify")
    async def verify(req: Request):
        values = req.headers.getlist("x-rag-proxy-token")
        if len(values) != 1 or not hmac.compare_digest(values[0].encode(), config.proxy_token.encode()):
            return error("无权访问认证检查。", 403)
        if not session(req):
            return error("请登录拥有者账号。", 401)
        value = await identity(req)
        if not is_owner(value):
            return error("该会话没有知识工作区的管理权限。", 403)
        return JSONResponse({"administrator": True}, headers={"X-Rag-User-Id": config.owner_id, "X-Rag-Role": "admin"})

    return app


def app_factory():
    return create_app(LoginConfig.from_env())
