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


class DemoDatasetTests(unittest.TestCase):
    def test_manifest_and_documents_are_complete(self) -> None:
        dataset = ROOT / "data" / "datasets" / "cmrc2018-demo"
        manifest = json.loads((dataset / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(len(manifest["documents"]), 24)
        self.assertEqual(sum(len(item["questions"]) for item in manifest["documents"]), 99)
        self.assertTrue(
            all((dataset / "documents" / item["file"]).is_file() for item in manifest["documents"])
        )

    def test_dataset_is_loaded_and_examples_are_exposed(self) -> None:
        info = json.loads(server_app.demo().body.decode("utf-8"))
        self.assertEqual(info["imported"], 24)
        self.assertEqual(info["question_count"], 99)
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
