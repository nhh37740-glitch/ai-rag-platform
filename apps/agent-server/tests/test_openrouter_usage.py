"""Compiled HTTP quota checks use inert credentials and never contact a model."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]

PUBLIC = r'''
import asyncio
import httpx
import server as s
from core_specifications import SpanEvent

calls = []
source = s.vector_store.list_documents()[0][0]
class Runtime:
    async def run(self, ctx, question, ids):
        calls.append(ctx)
        s.trace_store.record(SpanEvent(ctx.trace_id, "rag", 1, 2, meta={
            "knowledge_base_ids": ids, "hit_count": 1, "hits": [{"source_id": source}]}))
        return "grounded-answer"
s.public_demo.runtime_factory = Runtime

async def main():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=s.app), base_url="https://demo.test") as client:
        config = await client.get("/api/llm/config")
        assert config.status_code == 200
        assert config.json()["model"] == "openrouter/free"
        assert config.json()["free_models_only"] and config.json()["quota"]["remaining"] == 20
        assert "inert-server-credential" not in config.text
        invalid = await client.post("/api/demo/chat", json={"question":"x", "model":"paid/model"})
        assert invalid.status_code == 422 and s._web_quota_status()["used"] == 0
        for index in range(20):
            headers = {"origin":"https://demo.test", "x-deepseek-api-key":"inert-browser-key"} if index == 19 else {}
            response = await client.post("/api/demo/chat", json={"question":"question-" + str(index)}, headers=headers)
            assert response.status_code == 200, response.text
            assert response.json()["provider"] == "openrouter"
            assert response.json()["quota"]["used"] == index + 1
        denied = await client.post("/api/demo/chat", json={"question":"another-client"}, headers={"origin":"https://demo.test", "x-deepseek-api-key":"another-browser-key"})
        assert denied.status_code == 429 and int(denied.headers["retry-after"]) > 0
        assert denied.json()["detail"]["quota"]["remaining"] == 0
        assert len(calls) == 20
asyncio.run(main())
'''

PRIVATE = r'''
import asyncio
import httpx
import server as s
from unittest.mock import AsyncMock, patch
from core_specifications import RequestContext
for index in range(18):
    s.daily_query_quota.reserve(RequestContext("t", "r", "client-"+str(index)))
async def main():
    with patch.object(s.runtime, "run", new=AsyncMock(return_value="answer")) as model:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=s.app), base_url="http://localhost") as client:
            invalid = await client.post("/api/chat", json={"message":""})
            assert invalid.status_code == 422 and s._web_quota_status()["used"] == 18
            chat = await client.post("/api/chat", json={"message":"question","user_id":"another"})
            assert chat.status_code == 200 and chat.json()["quota"]["remaining"] == 1
            stream = await client.get("/api/chat/stream", params={"message":"stream-question"})
            assert stream.status_code == 200 and '"remaining": 0' in stream.text
            denied = await client.post("/api/chat", json={"message":"question","session_id":"new"}, headers={"origin":"http://localhost","x-deepseek-api-key":"inert-override"})
            assert denied.status_code == 429 and model.await_count == 2
asyncio.run(main())
'''


class OpenRouterQuotaHTTPTests(unittest.TestCase):
    def run_script(self, code, directory, public=True):
        env = dict(os.environ, PYTHONPATH=str(ROOT / "apps/agent-server"),
                   PUBLIC_DEMO="1" if public else "0", LLM_PROVIDER="openrouter",
                   OPENROUTER_API_KEY="inert-server-credential", OPENROUTER_MODEL="openrouter/free",
                   RAG_LLM_ENV_FILE="", RAG_ADMIN_AUTH="local", RAG_EMBED="hash", STATE_DIR=directory,
                   DB_PATH=str(Path(directory) / "memory.sqlite"),
                   VECTOR_DB_PATH=str(Path(directory) / "vectors.sqlite"), WEB_QUOTA_STATE_DIR=str(Path(directory) / "quota"),
                   INDEX_PATH=str(Path(directory) / "absent.json"))
        result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_public_twenty_requests_then_block_and_persist_after_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            self.run_script(PUBLIC, directory)
            self.run_script('import server as s; assert s._web_quota_status()["used"] == 20; assert s._web_quota_status()["remaining"] == 0', directory)

    def test_private_chat_stream_and_browser_key_share_same_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            self.run_script(PRIVATE, directory, public=False)
