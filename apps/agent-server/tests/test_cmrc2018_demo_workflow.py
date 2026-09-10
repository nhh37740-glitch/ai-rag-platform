from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SERVER = ROOT / "apps" / "agent-server"
sys.path.insert(0, str(SERVER))
os.environ["RAG_EMBED"] = "hash"

import server as server_app  # noqa: E402
from core_contracts import RequestContext  # noqa: E402
from rag_core import retrieve  # noqa: E402


class DemoKnowledgeBaseTests(unittest.TestCase):
    def test_manifest_and_documents_are_complete(self) -> None:
        knowledge_base = ROOT / "data" / "kb" / "cmrc2018-demo"
        manifest = json.loads((knowledge_base / "knowledge-base-manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(len(manifest["documents"]), 24)
        self.assertEqual(sum(len(item["questions"]) for item in manifest["documents"]), 99)
        self.assertTrue(
            all((knowledge_base / "knowledge-documents" / item["file"]).is_file() for item in manifest["documents"])
        )

    def test_knowledge_base_is_loaded_and_questions_are_exposed(self) -> None:
        info = json.loads(server_app.demo().body.decode("utf-8"))
        self.assertEqual(info["imported"], 24)
        self.assertEqual(info["question_count"], 99)
        self.assertEqual(info["knowledge_base"], "data/kb/cmrc2018-demo")
        self.assertEqual(len(info["suggested_questions"]), 8)
        self.assertEqual(info["purpose"], "project-demo-only")

        result = retrieve(
            RequestContext("trace", "request"),
            "什么是静电感应？",
            server_app.vector_store,
            top_k=3,
        )
        self.assertTrue(any("静电感应" in item.source_id for item in result.citations))


if __name__ == "__main__":
    unittest.main()
