"""Public HTTP adapter; module implementations remain behind their binary facades."""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections import OrderedDict, deque

from auth_facade import AuthService
from admin_workspace import public_read_path

from core_specifications import RequestContext
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse


class PublicDemoBoundary:
    """Deny every route/method except the small public read-only surface."""

    def __init__(self, app, *, auth_service=None):
        self.app = app
        self.auth_service = auth_service if auth_service is not None else AuthService()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path, method = scope["path"], scope["method"]
        headers = {key.lower() for key, _ in scope.get("headers", [])}
        credential = b"authorization" in headers or (
            b"x-deepseek-api-key" in headers and not (method == "POST" and path == "/api/demo/chat")
        )
        # StaticFiles shares the private webui directory. Only the public page's
        # styles and script are needed; do not serve the private UI or its script.
        readable = path in {
            "/", "/api/demo", "/api/llm/config",
            "/static/knowledge_demo.css",
            "/static/public_demo.css",
            "/static/public_demo.js",
        }
        readable = readable or public_read_path(path)
        readable = readable or (
            path.startswith("/api/trace/") and len(path.split("/")) == 4
        )
        allowed = (method == "GET" and readable) or (
            method == "POST" and path == "/api/demo/chat"
        )
        request_id = uuid.uuid4().hex
        ctx = RequestContext(request_id, request_id, "guest")
        principal = self.auth_service.guest(ctx)
        try:
            self.auth_service.authorize(ctx, principal, "query" if method == "POST" and path == "/api/demo/chat" else "read" if allowed else "write")
        except PermissionError:
            allowed = False
        if credential or not allowed:
            response = JSONResponse({"detail": "游客只允许公开知识库读取和查询"}, status_code=403, headers={"Cache-Control": "no-store"})
            await response(scope, receive, send)
            return
        scope.setdefault("state", {})["auth_principal"] = principal
        scope["state"]["auth_context"] = ctx
        await self.app(scope, receive, send)


class PublicDemo:
    def __init__(self, *, runtime_factory, tracing, questions, provider, embedding, kb_id,
                 reserve_query=None, quota_status=None):
        self.runtime_factory = runtime_factory
        self.tracing = tracing
        self.questions = frozenset(questions)
        self.provider = provider
        self.embedding = embedding
        self.kb_id = kb_id
        self.reserve_query = reserve_query
        self.quota_status = quota_status
        self.timeout_seconds = 90
        self.cache_seconds = 300
        self._cache = OrderedDict()
        self._active = None
        self._trace_ids = deque(maxlen=256)

    def trace(self, trace_id):
        if trace_id not in self._trace_ids:
            return []
        return [event.__dict__ for event in self.tracing.get(trace_id)]

    def _has_retrieval(self, trace_id):
        for event in self.tracing.get(trace_id):
            meta = event.meta
            if event.span != "rag" or event.status != "ok" or event.error:
                continue
            hits = meta.get("hits")
            hit_count = meta.get("hit_count")
            if meta.get("knowledge_base_ids") != [self.kb_id]:
                continue
            if not isinstance(hit_count, int) or hit_count <= 0 or not isinstance(hits, list) or not hits:
                continue
            if all(
                isinstance(hit, dict)
                and str(hit.get("source_id", "")).startswith(self.kb_id + "/")
                for hit in hits
            ):
                return True
        return False

    async def _question(self, request: Request):
        if request.query_params:
            raise HTTPException(422, "不允许附加查询参数")
        if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
            raise HTTPException(422, "请求必须是 JSON")
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > 16384:
                raise HTTPException(422, "请求正文不能超过 16 KiB")
            body.extend(chunk)
        try:
            # Duplicate fields are invalid too; do not silently select one question.
            def unique_object(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError("重复字段")
                    result[key] = value
                return result

            payload = json.loads(body, object_pairs_hook=unique_object)
        except (ValueError, UnicodeError):
            raise HTTPException(422, "无效的 JSON") from None
        if not isinstance(payload, dict) or set(payload) != {"question"}:
            raise HTTPException(422, "请求只允许 question 字段")
        question = payload["question"]
        if not isinstance(question, str) or not question.strip() or len(question) > 1024:
            raise HTTPException(422, "question 必须为非空且不超过 1024 字符的文本")
        return question

    async def chat(self, request: Request, *, temporary_key=False):
        question = await self._question(request)
        cache_allowed = not temporary_key and question in self.questions
        if cache_allowed:
            now = time.monotonic()
            for old_question, (expires, _) in list(self._cache.items()):
                if expires <= now:
                    del self._cache[old_question]
        cached = self._cache.get(question) if cache_allowed else None
        if cached and self.trace(cached[1]["trace_id"]):
            return JSONResponse({**cached[1], "cache_hit": True,
                                 "quota": self.quota_status() if self.quota_status else None}, headers={"Cache-Control": "no-store"})
        # No await between the busy check and assignment: atomic within one event loop.
        if self._active is not None and not self._active.done():
            raise HTTPException(429, "演示正在回答，请稍后重试")
        trace_id = uuid.uuid4().hex
        self._trace_ids.append(trace_id)
        ctx = RequestContext(
            trace_id=trace_id, request_id=uuid.uuid4().hex,
            user_id=uuid.uuid4().hex, session_id=uuid.uuid4().hex,
        )
        if self.reserve_query:
            self.reserve_query(ctx)
        # Keep the user's question unchanged. The internal prefix requests a
        # document lookup, including for MockProvider's keyword tool selection.
        grounded_request = "请查阅内置知识库资料，回答：" + question
        task = asyncio.create_task(self.runtime_factory().run(ctx, grounded_request, [self.kb_id]))
        self._active = task
        try:
            # wait(), rather than wait_for(), returns at the deadline even if a
            # provider delays cancellation. Such a task continues holding the slot.
            done, _ = await asyncio.wait({task}, timeout=self.timeout_seconds)
            if not done:
                task.cancel()
                task.add_done_callback(self._consume_result)
                raise HTTPException(504, "演示回答超过 90 秒，请稍后重试")
            answer = task.result()
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(502, "模型或检索执行失败，请稍后重试") from None
        except asyncio.CancelledError:
            task.cancel()
            task.add_done_callback(self._consume_result)
            raise
        finally:
            if task.done() and self._active is task:
                self._active = None
        if not isinstance(answer, str) or not answer.strip() or not self._has_retrieval(trace_id):
            raise HTTPException(502, "未获得成功的内置资料检索结果")
        result = {
            "answer": answer, "trace_id": trace_id, "knowledge_base_ids": [self.kb_id],
            "provider": "openrouter" if self.provider == "openrouter" else "deepseek" if temporary_key else self.provider, "embedding": self.embedding,
            "read_only": True, "cache_hit": False,
            "quota": self.quota_status() if self.quota_status else None,
        }
        if cache_allowed:
            self._cache[question] = (time.monotonic() + self.cache_seconds, result)
        return JSONResponse(result, headers={"Cache-Control": "no-store"})

    @staticmethod
    def _consume_result(task):
        if not task.cancelled():
            task.exception()
