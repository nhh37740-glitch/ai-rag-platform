"""Run HTTP checks in fresh processes so every boot enforces the binary boundary."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SERVER = ROOT / "apps" / "agent-server"


PUBLIC_CHECKS = r'''
import asyncio
import json
import time
from pathlib import Path
from unittest.mock import patch

# Guard startup filesystem access, even when private files/directories exist.
root = Path.cwd()
old_glob, old_iterdir, old_read = Path.glob, Path.iterdir, Path.read_text
def guarded_glob(self, *args, **kwargs):
    assert self != root / "data" / "kb", "public boot scanned root local documents"
    return old_glob(self, *args, **kwargs)
def guarded_iterdir(self, *args, **kwargs):
    assert self != root / "data" / "kb" / "user-notebooks", "public boot scanned private notebooks"
    return old_iterdir(self, *args, **kwargs)
def guarded_read(self, *args, **kwargs):
    assert self != root / ".env", "public boot read private dotenv"
    assert self.name != "private-index.json", "public boot migrated private index"
    return old_read(self, *args, **kwargs)
with patch.object(Path, "glob", guarded_glob), patch.object(Path, "iterdir", guarded_iterdir), patch.object(Path, "read_text", guarded_read):
    import server as s

import httpx
from core_specifications import RequestContext, SpanEvent
assert s.DEMO_KB_ID == "cmrc2018-demo"
assert type(s.provider).__name__ == "MockProvider", "mock must override any configured server key"
assert len(s.runtime.tool_definitions(RequestContext("t", "r"))) == 5
assert all(source.startswith("cmrc2018-demo/") for source, _ in s.vector_store.list_documents())
original = s.provider

class NoRetrieval:
    async def generate(self, ctx, messages, tools=None):
        return "unverified answer", []

class Failure:
    async def generate(self, ctx, messages, tools=None):
        raise RuntimeError("secret-sentinel-must-not-leak")

class Blocking:
    def __init__(self):
        self.entered, self.release = asyncio.Event(), asyncio.Event()
        self.contexts = []
    async def generate(self, ctx, messages, tools=None):
        self.contexts.append(ctx)
        self.entered.set()
        await self.release.wait()
        return await original.generate(ctx, messages, tools)

async def main():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=s.app), base_url="http://demo.test") as client:
        info = (await client.get("/api/demo")).json()
        assert info["public_demo"] and info["read_only"]
        assert (info["provider"], info["embedding"]) == ("mock", "hash")
        assert len(info["suggested_questions"]) == 8
        questions = [item["question"] for item in info["suggested_questions"]]
        assert s.index().path.endswith("public_demo.html")
        page = await client.get("/")
        assert page.status_code == 200
        assert 'class="workspace public-workspace"' in page.text
        assert 'id="sources-panel"' in page.text and 'id="studio-panel"' in page.text
        assert 'id="question-options"' in page.text and 'id="answer-content"' in page.text
        for element in ["identity-badge", "admin-login-link", "document-list", "question-input", "document-dialog", "document-content", "next-document-page"]:
            assert 'id="' + element + '"' in page.text, element
        for forbidden in ["knowledge_demo.js", 'id="upload-form"', 'id="key-config-input"', 'id="notebook-name"', 'id="m"']:
            assert forbidden not in page.text
        for asset in ["/static/knowledge_demo.css", "/static/public_demo.css", "/static/public_demo.js"]:
            assert (await client.get(asset)).status_code == 200, asset
        for asset in ["/static/index.html", "/static/knowledge_demo.js", "/static/public_demo.html", "/static/no-such-file"]:
            assert (await client.get(asset)).status_code == 403, asset
        config = await client.get("/api/llm/config")
        assert config.status_code == 200 and not config.json()["server_key_configured"]
        for method, path in [("POST", "/api/chat"), ("GET", "/api/chat/stream"), ("POST", "/api/notebooks"), ("POST", "/api/notebooks/anything/files"), ("GET", "/api/notebooks/private/documents"), ("GET", "/api/notebooks/private/suggestions"), ("GET", "/api/uploads/private"), ("GET", "/docs"), ("GET", "/openapi.json"), ("DELETE", "/api/demo"), ("HEAD", "/api/demo")]:
            assert (await client.request(method, path)).status_code == 403, (method, path)
        for header in ["authorization", "x-deepseek-api-key"]:
            assert (await client.post("/api/demo/chat", json={"question": questions[0]}, headers={header: "placeholder"})).status_code == 403
        assert (await client.get("/api/admin/session")).status_code == 403
        for payload in [{}, [], {"question": 4}, {"question": ""}, {"question": " \n\t"}, {"question": "x" * 1025}, {"question": questions[0], "knowledge_base_ids": []}, {"question": questions[0], "user_id": "private"}, {"question": questions[0], "key": "placeholder"}]:
            assert (await client.post("/api/demo/chat", json=payload)).status_code == 422
        for body, content_type in [("{}", "text/plain"), ("{", "application/json"), (" " * 16385, "application/json"), ('{"question":"x","question":"x"}', "application/json")]:
            assert (await client.post("/api/demo/chat", content=body, headers={"content-type": content_type})).status_code == 422
        assert (await client.post("/api/demo/chat?scope=private", json={"question": questions[0]})).status_code == 422

        identity = await client.get("/api/auth/session")
        assert identity.status_code == 200 and identity.headers["cache-control"] == "no-store"
        assert identity.json()["role"] == "guest" and not identity.json()["administrator"]
        assert identity.json()["read_only"] and identity.json()["permissions"] == ["read", "query"]
        assert identity.json()["allowed_notebook_ids"] == [s.DEMO_KB_ID]
        assert "proof" not in identity.text and "token" not in identity.text
        forged = await client.get("/api/auth/session", headers={"x-rag-user-id": "owner", "x-rag-role": "admin", "x-rag-proxy-token": "forged"})
        assert forged.status_code == 200 and forged.json()["role"] == "guest"
        notebooks = (await client.get("/api/notebooks")).json()["notebooks"]
        assert [notebook["id"] for notebook in notebooks] == [s.DEMO_KB_ID]
        documents = (await client.get("/api/notebooks/" + s.DEMO_KB_ID + "/documents")).json()["documents"]
        assert len(documents) == 24 and all(doc["source_id"].startswith(s.DEMO_KB_ID + "/") for doc in documents)
        assert (await client.get("/api/notebooks/" + s.DEMO_KB_ID + "/suggestions")).status_code == 200
        source_id = documents[0]["source_id"]
        document_id = source_id.partition("/")[2]
        original_chunks = s.vector_store.document_chunks(source_id)
        ctx = RequestContext("public-pagination", "public-pagination", "guest")
        try:
            chunks = ["公开文档第" + str(index) + "块" for index in range(45)]
            s.vector_store.add(source_id, chunks, s.rag_service.embed_texts(ctx, chunks))
            endpoint = "/api/demo/documents/" + document_id
            for offset, expected_length, next_offset in [(0, 20, 20), (20, 20, 40), (40, 5, None), (100, 0, None)]:
                response = await client.get(endpoint, params={"offset": offset})
                assert response.status_code == 200, response.text
                page = response.json()
                assert page["source_id"] == source_id and page["document_id"] == document_id
                assert page["contexts"] == chunks[offset:offset + 20] and len(page["contexts"]) == expected_length
                assert page["offset"] == offset and page["total_chunks"] == 45
                assert page["next_offset"] == next_offset and page["truncated"] == (next_offset is not None)
                assert response.headers["cache-control"] == "no-store"
            for params in [{"offset": -1}, {"offset": "true"}, {"offset": 0, "scope": "private"}, {"max_chunks": 100}]:
                assert (await client.get(endpoint, params=params)).status_code == 422
            assert (await client.get(endpoint + "?offset=0&offset=20")).status_code == 422
            assert (await client.get("/api/demo/documents/private-doc")).status_code == 404
            assert (await client.get("/api/demo/documents/private%2Fdoc")).status_code == 403
        finally:
            s.vector_store.add(source_id, original_chunks, s.rag_service.embed_texts(ctx, original_chunks))

        for free_question in ["请概括静电感应的文档内容。", questions[0] + " ", "中文" * 512]:
            first = await client.post("/api/demo/chat", json={"question": free_question})
            second = await client.post("/api/demo/chat", json={"question": free_question})
            assert first.status_code == second.status_code == 200, first.text + second.text
            assert not first.json()["cache_hit"] and not second.json()["cache_hit"]
            assert first.json()["trace_id"] != second.json()["trace_id"]
            assert free_question not in s.public_demo._cache
            assert first.json()["knowledge_base_ids"] == [s.DEMO_KB_ID]
        escaped = await client.post(
            "/api/demo/chat", content=json.dumps({"question": "文" * 1024}, ensure_ascii=True),
            headers={"content-type": "application/json"},
        )
        assert escaped.status_code == 200 and not escaped.json()["cache_hit"], escaped.text

        response = await client.post("/api/demo/chat", json={"question": questions[0]})
        assert response.status_code == 200, response.text
        result = response.json()
        assert response.headers["cache-control"] == "no-store"
        assert result["answer"] and not result["cache_hit"]
        assert result["knowledge_base_ids"] == ["cmrc2018-demo"]
        events = (await client.get("/api/trace/" + result["trace_id"])).json()
        rag = [e for e in events if e["span"] == "rag" and e["status"] == "ok"]
        assert any(e["meta"]["hit_count"] > 0 and e["meta"]["hits"] for e in rag)
        assert all(hit["source_id"].startswith("cmrc2018-demo/") for e in rag for hit in e["meta"].get("hits", []))
        again = (await client.post("/api/demo/chat", json={"question": questions[0]})).json()
        assert again == {**result, "cache_hit": True}
        # Browser credentials are allowed only on this route and secure same origin.
        for origin in ["http://demo.test", "https://elsewhere.test", "https://demo.test/path", "null"]:
            rejected = await client.post("/api/demo/chat", json={"question": questions[0]}, headers={"origin": origin, "x-deepseek-api-key": "temporary-placeholder"})
            assert rejected.status_code == 403
        for value in [" ", "x" * 513]:
            rejected = await client.post("/api/demo/chat", json={"question": questions[0]}, headers={"origin": "https://demo.test", "x-deepseek-api-key": value})
            assert rejected.status_code == 422
        assert (await client.get("/api/demo", headers={"x-deepseek-api-key": "placeholder"})).status_code == 403
        keys = []
        def request_model(key, base, model):
            keys.append(key)
            return original
        with patch("request_provider.make_provider", side_effect=request_model):
            keyed = []
            for key in ["first-placeholder", "second-placeholder"]:
                response = await client.post("/api/demo/chat", json={"question": questions[0]}, headers={"origin": "https://demo.test", "x-deepseek-api-key": key})
                assert response.status_code == 200, response.text
                keyed.append(response.json())
            assert keys == ["first-placeholder", "second-placeholder"]
            assert all(item["provider"] == "deepseek" and not item["cache_hit"] for item in keyed)
            assert len({item["trace_id"] for item in keyed} | {result["trace_id"]}) == 3
        assert s.request_provider.for_request() is s.request_provider
        assert s.request_provider._provider() is original
        assert s.public_demo._cache[questions[0]][1] == result
        assert (await client.post("/api/demo/chat", json={"question": questions[0]})).json() == {**result, "cache_hit": True}
        # Upstream exception data is sanitized before it reaches error spans.
        with patch("request_provider.make_provider", return_value=Failure()):
            response = await client.post("/api/demo/chat", json={"question": questions[0]}, headers={"origin": "https://demo.test", "x-deepseek-api-key": "secret-sentinel-must-not-leak"})
            assert response.status_code == 502 and "secret-sentinel" not in response.text
            latest_trace = s.public_demo._trace_ids[-1]
            assert "secret-sentinel" not in json.dumps(s.public_demo.trace(latest_trace))
        assert s.request_provider.for_request() is s.request_provider
        assert s.request_provider._provider() is original
        s.trace_store.record(SpanEvent("private-trace", "agent", 1, 2))
        assert (await client.get("/api/trace/private-trace")).json() == []

        s.public_demo._cache.clear()
        from rag_core import InMemoryVectorStore
        populated_rag_service = s.rag_service
        s.rag_service = s.RagService(InMemoryVectorStore(), s.trace_store)
        assert (await client.post("/api/demo/chat", json={"question": questions[0]})).status_code == 502
        assert not s.public_demo._cache
        s.rag_service = populated_rag_service
        try:
            s._read_knowledge_document("private/doc", ctx=RequestContext("outside-tool", "r"), runtime_context={"knowledge_base_ids": ["private"]})
            raise AssertionError("read tool accepted source outside CMRC")
        except ValueError:
            pass
        s.provider = NoRetrieval()
        assert (await client.post("/api/demo/chat", json={"question": questions[0]})).status_code == 502
        assert not s.public_demo._cache
        s.provider = Failure()
        failed = await client.post("/api/demo/chat", json={"question": questions[0]})
        assert failed.status_code == 502 and "secret-sentinel" not in failed.text

        # Even nominally successful spans cannot claim private/no-hit evidence.
        for tid, meta, status in [("outside", {"knowledge_base_ids": [s.DEMO_KB_ID], "hit_count": 1, "hits": [{"source_id": "private/doc"}]}, "ok"), ("empty", {"knowledge_base_ids": [s.DEMO_KB_ID], "hit_count": 1, "hits": []}, "ok"), ("failed", {"knowledge_base_ids": [s.DEMO_KB_ID], "hit_count": 1, "hits": [{"source_id": s.DEMO_KB_ID + "/doc"}]}, "error")]:
            s.trace_store.record(SpanEvent(tid, "rag", 1, 2, status=status, meta=meta))
            assert not s.public_demo._has_retrieval(tid)

        blocking = Blocking()
        s.provider = blocking
        pending = asyncio.create_task(client.post("/api/demo/chat", json={"question": questions[0]}))
        await asyncio.wait_for(blocking.entered.wait(), 2)
        assert (await client.post("/api/demo/chat", json={"question": questions[1]})).status_code == 429
        blocking.release.set()
        assert (await pending).status_code == 200
        s.public_demo._cache.clear()
        blocking = Blocking()
        s.provider = blocking
        s.public_demo.timeout_seconds = 0.01
        assert (await client.post("/api/demo/chat", json={"question": questions[0]})).status_code == 504
        await asyncio.sleep(0)
        assert not s.public_demo._cache
        s.public_demo.timeout_seconds = 90

        # TTL expiration reruns a real Agent, with new identities and original trace.
        s.provider = original
        first = (await client.post("/api/demo/chat", json={"question": questions[0]})).json()
        with patch("public_demo.time.monotonic", return_value=time.monotonic() + 301):
            second = (await client.post("/api/demo/chat", json={"question": questions[0]})).json()
        assert not second["cache_hit"] and first["trace_id"] != second["trace_id"]
        captures = []
        grounded_inputs = set()
        # Capture contexts through a provider, preserving the compiled Runtime.
        class Capture:
            async def generate(self, ctx, messages, tools=None):
                if not captures or captures[-1] != ctx:
                    captures.append(ctx)
                grounded_inputs.update(message.content for message in messages if message.role == "user")
                return await original.generate(ctx, messages, tools)
        s.provider = Capture()
        for question in questions:
            s.public_demo._cache.pop(question, None)
            assert (await client.post("/api/demo/chat", json={"question": question})).status_code == 200
        assert len(s.public_demo._cache) <= len(questions)
        assert len({ctx.user_id for ctx in captures}) == len(questions)
        assert len({ctx.session_id for ctx in captures}) == len(questions)
        assert len({ctx.request_id for ctx in captures}) == len(questions)
        assert all(ctx.user_id != "anon" and ctx.session_id != "s1" for ctx in captures)
        assert grounded_inputs == {"请查阅内置知识库资料，回答：" + question for question in questions}

asyncio.run(main())
'''


class PublicDemoIntegrationTests(unittest.TestCase):
    def run_process(self, code, *, public=True, provider="mock", key="", expected=0, error=None):
        scratch = ROOT / "data" / "_tests"
        scratch.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="public-demo-", dir=scratch) as state:
            env = dict(os.environ)
            env.update({
                "PYTHONPATH": str(SERVER), "PUBLIC_DEMO": "1" if public else "0",
                "DEMO_PROVIDER": provider, "DEEPSEEK_API_KEY": key,
                "LLM_PROVIDER": "", "OPENROUTER_API_KEY": "", "RAG_LLM_ENV_FILE": "",
                "RAG_EMBED": "hash", "STATE_DIR": state,
                "DB_PATH": str(Path(state) / "app.sqlite"),
                "VECTOR_DB_PATH": str(Path(state) / "vector.sqlite"),
                "INDEX_PATH": str(Path(state) / "private-index.json"),
                "DEMO_KB_ID": "attempted-private-scope" if public else "cmrc2018-demo",
            })
            Path(env["INDEX_PATH"]).write_text("invalid-private-json", encoding="utf-8")
            if not public:
                Path(env["INDEX_PATH"]).unlink()
            result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, text=True, capture_output=True, timeout=90)
            # Test subprocesses have only an empty key or an inert placeholder.
            self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
            if error:
                self.assertIn(error, result.stderr)

    def test_public_compiled_http_boundary_and_real_rag(self):
        self.run_process(PUBLIC_CHECKS, key="placeholder-explicit-mock")

    def test_deepseek_without_server_key_fails_closed(self):
        self.run_process('import server', provider="deepseek", expected=1, error="DeepSeek 缺少服务端凭据")

    def test_invalid_public_provider_fails_closed(self):
        self.run_process('import server', provider="invalid", expected=1, error="LLM_PROVIDER 必须为 mock、deepseek 或 openrouter")

    def test_private_routes_and_request_provider_remain_available(self):
        self.run_process(r'''
import asyncio
import httpx
import server as s
from core_specifications import RequestContext
assert len(s.runtime.tool_definitions(RequestContext("t", "r"))) == 7
assert s.runtime.provider is s.request_provider
assert s.index().path.endswith("index.html")
async def main():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=s.app), base_url="http://localhost") as client:
        assert (await client.get("/api/notebooks")).status_code == 200
        assert (await client.post("/api/demo/chat", json={"question":"x"})).status_code == 404
        result = await client.post("/api/chat", json={"message":"什么是静电感应？"})
        assert result.status_code == 200 and result.json()["answer"]
        info = (await client.get("/api/demo")).json()
        assert not info["public_demo"] and not info["read_only"]
asyncio.run(main())
''', public=False)
