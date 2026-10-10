"""Meaningful private ingress checks; run in the server Docker build."""
from __future__ import annotations

import sys
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import httpx
from fastapi.responses import JSONResponse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from admin_workspace import AdminWorkspaceBoundary

TOKEN = "test-only-private-gateway-proof-123456789"
ORIGIN = "https://portfolio.test:8443"
OWNER = "owner-account"
HEADERS = {"x-rag-proxy-token": TOKEN, "x-rag-user-id": OWNER, "x-rag-role": "admin"}


class AdminBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.calls = []

        async def private_app(scope, receive, send):
            self.calls.append(scope)
            response = JSONResponse({"owner": scope.get("state", {}).get("admin_owner_id")})
            await response(scope, receive, send)

        app = AdminWorkspaceBoundary(private_app, proxy_token=TOKEN, owner_id=OWNER, origin=ORIGIN)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN)

    async def asyncTearDown(self):
        await self.client.aclose()

    async def test_anonymous_and_forged_identity_never_reach_private_routes(self):
        for path in ["/", "/static/knowledge_demo.js", "/api/notebooks/private/documents", "/api/uploads/progress", "/api/trace/private", "/docs", "/openapi.json", "/unknown"]:
            self.assertEqual((await self.client.get(path)).status_code, 403, path)
        for replacement in [
            {"x-rag-proxy-token": "forged"}, {"x-rag-user-id": "other-admin"},
            {"x-rag-role": "user"}, {"x-rag-proxy-token": ""},
        ]:
            response = await self.client.get("/api/notebooks", headers={**HEADERS, **replacement})
            self.assertEqual(response.status_code, 403)
        duplicates = list(HEADERS.items()) + [("X-Rag-User-Id", OWNER)]
        self.assertEqual((await self.client.get("/api/notebooks", headers=duplicates)).status_code, 403)
        self.assertFalse(self.calls)

    async def test_guest_can_read_only_public_routes_and_session(self):
        for path in [
            "/api/auth/session", "/api/notebooks",
            "/api/notebooks/cmrc2018-demo/documents",
            "/api/notebooks/cmrc2018-demo/suggestions",
            "/api/demo/documents/008-demo",
        ]:
            response = await self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertIsNone(response.json()["owner"])
            principal = self.calls[-1]["state"]["auth_principal"]
            self.assertEqual(principal.role, "guest")
            self.assertEqual(principal.proof, "")
        response = await self.client.post("/api/notebooks", json={"name": "guest cannot write"})
        self.assertEqual(response.status_code, 403)

    async def test_writes_and_sse_require_same_origin_before_body_processing(self):
        for method, path in [("POST", "/api/notebooks"), ("POST", "/api/notebooks/private/files"), ("POST", "/api/chat"), ("GET", "/api/chat/stream"), ("DELETE", "/private")]:
            for csrf in [{}, {"origin": "https://attacker.test"}, {"origin": ORIGIN, "sec-fetch-site": "cross-site"}]:
                response = await self.client.request(method, path, headers={**HEADERS, **csrf}, content=b"invalid body")
                self.assertEqual(response.status_code, 403, (method, path, csrf))
        self.assertFalse(self.calls)

    async def test_verified_owner_and_public_health_metadata(self):
        response = await self.client.get("/api/demo")
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["owner"])
        for method, path in [("GET", "/"), ("GET", "/api/notebooks"), ("POST", "/api/notebooks"), ("POST", "/api/notebooks/private/files")]:
            response = await self.client.request(method, path, headers={**HEADERS, "origin": ORIGIN})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["owner"], OWNER)
            self.assertEqual(response.headers["cache-control"], "no-store")

    def test_invalid_server_configuration_fails_closed(self):
        for token, owner, origin in [("", OWNER, ORIGIN), ("short", OWNER, ORIGIN), (TOKEN, "", ORIGIN), (TOKEN, " owner ", ORIGIN), (TOKEN, OWNER, "http://portfolio.test"), (TOKEN, OWNER, ORIGIN + "/path"), (TOKEN, OWNER, "https://user:password@portfolio.test")]:
            with self.assertRaises(RuntimeError):
                AdminWorkspaceBoundary(None, proxy_token=token, owner_id=owner, origin=origin)


class AdminNotebookIntegrationTests(unittest.TestCase):
    def test_owner_imports_real_document_and_keeps_it_out_of_public_scope(self):
        root = Path(__file__).resolve().parents[3]
        scratch = root / "data" / "_tests"
        scratch.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="admin-workspace-", dir=scratch) as state:
            env = dict(os.environ)
            env.update({
                "PYTHONPATH": str(root / "apps" / "agent-server"),
                "PUBLIC_DEMO": "0", "RAG_ADMIN_AUTH": "proxy",
                "RAG_ADMIN_PROXY_TOKEN": TOKEN, "RAG_ADMIN_OWNER_ID": OWNER,
                "RAG_ADMIN_ORIGIN": ORIGIN,
                "DEEPSEEK_API_KEY": "", "RAG_EMBED": "hash", "STATE_DIR": state,
                "DB_PATH": str(Path(state) / "app.sqlite"),
                "VECTOR_DB_PATH": str(Path(state) / "vector.sqlite"),
                "INDEX_PATH": str(Path(state) / "missing-index.json"),
            })
            result = subprocess.run(
                [sys.executable, "-c", PRIVATE_IMPORT_CHECKS], cwd=root, env=env,
                text=True, capture_output=True, timeout=90,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


PRIVATE_IMPORT_CHECKS = r'''
import asyncio
import json
import os
from pathlib import Path
import httpx
import server as s

owner = os.environ["RAG_ADMIN_OWNER_ID"]
origin = os.environ["RAG_ADMIN_ORIGIN"]
headers = {"x-rag-proxy-token": os.environ["RAG_ADMIN_PROXY_TOKEN"], "x-rag-user-id": owner, "x-rag-role": "admin", "origin": origin}
# Keep tests wholly inside their fresh private state, including notebook files.
s.USER_NOTEBOOKS_DIR = Path(os.environ["STATE_DIR"]) / "notebooks"
s.AGENT_FILES_DIR = Path(os.environ["STATE_DIR"]) / "agent-files"
contexts = []
original = s.request_provider._default
class Capture:
    async def generate(self, ctx, messages, tools=None):
        contexts.append(ctx)
        return await original.generate(ctx, messages, tools)
s.request_provider._default = Capture()

async def main():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=s.app), base_url=origin) as client:
        visitor = await client.get("/api/auth/session")
        assert visitor.status_code == 200 and visitor.json()["role"] == "guest"
        assert visitor.json()["permissions"] == ["read", "query"]
        assert visitor.json()["allowed_notebook_ids"] == [s.DEMO_KB_ID]
        assert (await client.get("/api/notebooks")).status_code == 200
        denied = await client.post("/api/notebooks", json={"name": "blocked"})
        assert denied.status_code == 403 and not s.USER_NOTEBOOKS_DIR.exists()
        assert (await client.get("/static/knowledge_demo.js")).status_code == 403
        session = await client.get("/api/admin/session", headers=headers)
        assert session.status_code == 200 and session.json()["user_id"] == owner
        assert session.json()["administrator"] and session.headers["cache-control"] == "no-store"
        assert os.environ["RAG_ADMIN_PROXY_TOKEN"] not in session.text
        identity = await client.get("/api/auth/session", headers=headers)
        assert identity.json()["role"] == "admin" and identity.json()["administrator"]
        assert identity.json()["user_id"] == owner and not identity.json()["read_only"]
        assert "proof" not in identity.text and os.environ["RAG_ADMIN_PROXY_TOKEN"] not in identity.text
        response = await client.post("/api/notebooks", headers=headers, json={"name": "管理员导入验收", "description": "仅测试资料"})
        assert response.status_code == 201, response.text
        notebook = response.json()["id"]
        public_list = (await client.get("/api/notebooks")).json()["notebooks"]
        assert [item["id"] for item in public_list] == [s.DEMO_KB_ID]
        private_list = (await client.get("/api/notebooks", headers=headers)).json()["notebooks"]
        assert notebook in [item["id"] for item in private_list]
        assert (await client.get("/api/notebooks/" + notebook + "/documents")).status_code == 403
        assert (await client.get("/api/notebooks/" + notebook + "/suggestions")).status_code == 403
        assert (await client.get("/api/demo/documents/" + notebook)).status_code == 404
        path = "/api/notebooks/" + notebook + "/files?upload_id=owner-import"
        files = [("files", ("项目说明.md", "# 紫杉项目\n紫杉项目的发布方式是 Jenkins 完成模块测试后交付 Docker 镜像。\n".encode(), "text/markdown"))]
        assert (await client.post(path, files=files)).status_code == 403
        assert (await client.post(path, headers={**headers, "x-rag-user-id": "another-admin"}, files=files)).status_code == 403
        assert (await client.post(path, headers={**headers, "origin": "https://attacker.test"}, files=files)).status_code == 403
        assert not s._read_user_notebook(s._user_notebook_path(notebook))["documents"]
        imported = await client.post(path, headers=headers, files=files)
        assert imported.status_code == 201, imported.text
        assert len(imported.json()["imported"]) == 1
        progress = await client.get("/api/uploads/owner-import", headers=headers)
        assert progress.status_code == 200 and progress.json()["state"] == "done"
        docs = await client.get("/api/notebooks/" + notebook + "/documents", headers=headers)
        assert docs.status_code == 200 and len(docs.json()["documents"]) == 1
        result = await client.post("/api/chat", headers=headers, json={"message": "请查询文档，紫杉项目的发布方式是什么？", "session_id": "owner-import", "user_id": "spoofed-body-user", "knowledge_base_ids": [notebook]})
        assert result.status_code == 200, result.text
        assert contexts and all(ctx.user_id == owner for ctx in contexts)
        trace = (await client.get("/api/trace/" + result.json()["trace_id"], headers=headers)).json()
        hits = [hit for span in trace if span["span"] == "rag" for hit in span["meta"].get("hits", [])]
        assert hits and all(hit["source_id"].startswith(notebook + "/") for hit in hits), trace
        assert all(not source.startswith(notebook + "/") for source, _ in s.vector_store.list_documents([s.DEMO_KB_ID]))
        # Reload the same persistent SQLite/file state through the startup loader.
        reloaded, _ = s._load_kb()
        assert reloaded.list_documents([notebook])
        assert s._read_user_notebook(s._user_notebook_path(notebook))["documents"]
        assert (await client.get("/api/uploads/owner-import")).status_code == 403
        assert (await client.get("/api/trace/" + result.json()["trace_id"])).status_code == 403
        assert (await client.get("/api/demo")).status_code == 200

asyncio.run(main())
'''
