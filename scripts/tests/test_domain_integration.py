"""三域实际装配验收：临时入库、持久化、Agent 工具范围和追踪。"""
import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from core_specifications import RequestContext, RetrievalResult
from agent_facade import AgentService, make_provider
from data_facade import DataService
from rag_facade import RagService
from observability import make_trace_store

ROOT = Path(__file__).resolve().parents[2]


class DomainIntegrationTests(unittest.TestCase):
    def test_ingest_agent_trace_and_reopen(self):
        ctx = RequestContext("integration", "request", "user", "session")
        with tempfile.TemporaryDirectory() as temporary:
            data = DataService(temporary)
            trace = make_trace_store()
            rag = RagService(data.vector_store(ctx), trace)
            agent = AgentService(data, rag, trace, str(ROOT / "skills"), make_provider())
            try:
                receipt = rag.ingest_markdown(ctx, "# API\n\nAPI 认证需要 Bearer token。", "engineering/api-doc")
                self.assertGreater(receipt.chunk_count, 0)
                answer = asyncio.run(agent.run(ctx, "请查询 API 如何认证？", ["engineering"]))
                self.assertIn("api-doc", answer)
                spans = [s for s in trace.get(ctx.trace_id) if s.span == "rag"]
                self.assertTrue(spans)
                self.assertTrue(any(s.meta.get("hits") for s in spans))
                self.assertTrue(all(s.meta["knowledge_base_ids"] == ["engineering"] for s in spans))
                self.assertEqual(len(agent.history(ctx)), 2)
            finally:
                asyncio.run(agent.aclose(ctx))
                data.close(ctx)
            reopened = DataService(temporary)
            try:
                rag = RagService(reopened.vector_store(ctx), trace)
                result = rag.search(ctx, "Bearer", ["engineering"], mode="keyword")
                self.assertIsInstance(result, RetrievalResult)
                self.assertEqual(result.citations[0].source_id, receipt.source_id)
                self.assertTrue(reopened.memory_store(ctx).get(ctx, "user", "last_task"))
                self.assertEqual(rag.search(ctx, "Bearer", []).citations, [])
                with self.assertRaises(ValueError):
                    rag.read_document(ctx, receipt.source_id, ["outside"])
            finally:
                reopened.close(ctx)

    def test_cmrc_full_question_regression(self):
        kb = ROOT / "data/kb/cmrc2018-demo"
        manifest = json.loads((kb / "knowledge-base-manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(len(manifest["documents"]), 24)
        self.assertEqual(sum(len(doc["questions"]) for doc in manifest["documents"]), 99)
        ctx = RequestContext("cmrc-baseline", "baseline")
        with tempfile.TemporaryDirectory() as temporary:
            data = DataService(temporary)
            rag = RagService(data.vector_store(ctx), make_trace_store())
            try:
                for doc in manifest["documents"]:
                    rag.ingest(ctx, str(kb / "knowledge-documents" / doc["file"]), manifest["id"])
                for mode, minimum in [("vector", 95), ("keyword", 99), ("hybrid", 99)]:
                    misses = []
                    for doc in manifest["documents"]:
                        expected = manifest["id"] + "/" + Path(doc["file"]).stem
                        for i, question in enumerate(doc["questions"]):
                            result = rag.search(ctx, question, [manifest["id"]], 5, mode)
                            self.assertTrue(all(c.source_id.startswith(manifest["id"] + "/") for c in result.citations))
                            if expected not in {c.source_id for c in result.citations}:
                                misses.append(f"{doc['file']}#{i}: {question}")
                    self.assertGreaterEqual(99 - len(misses), minimum, f"{mode} 回归失败: {misses}")
            finally:
                data.close(ctx)
