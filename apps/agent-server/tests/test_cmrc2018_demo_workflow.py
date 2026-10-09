from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import Request


ROOT = Path(__file__).resolve().parents[3]
SERVER = ROOT / "apps" / "agent-server"
sys.path.insert(0, str(SERVER))
os.environ["RAG_EMBED"] = "hash"

import server as server_app  # noqa: E402
from core_specifications import RequestContext  # noqa: E402
from rag_core import retrieve  # noqa: E402


class DemoKnowledgeBaseTests(unittest.TestCase):
    def test_browser_key_origin_requires_https_or_loopback(self) -> None:
        def allowed(origin: str) -> bool:
            host = origin.split("://", 1)[-1]
            scope = {
                "type": "http",
                "headers": [(b"host", host.encode()), (b"origin", origin.encode())],
            }
            return server_app._web_key_origin_allowed(Request(scope))

        self.assertTrue(allowed("https://example.test"))
        self.assertTrue(allowed("http://localhost:8000"))
        self.assertTrue(allowed("http://127.0.0.1:8000"))
        self.assertTrue(allowed("http://[::1]:8000"))
        self.assertFalse(allowed("http://example.test"))
        self.assertFalse(allowed("http://localhost.example.test"))
        self.assertFalse(allowed("null"))
        self.assertFalse(server_app._web_key_origin_allowed(Request({
            "type": "http", "headers": [(b"host", b"example.test")],
        })))

    def test_llm_config_reports_only_masked_server_status(self) -> None:
        with patch.object(server_app, "API_KEY", "secret-sentinel"):
            response = server_app.llm_config()
        payload = json.loads(response.body)
        self.assertEqual(payload, {"server_key_configured": True, "model": server_app.MODEL})
        self.assertNotIn("secret-sentinel", response.body.decode("utf-8"))
        self.assertEqual(response.headers["cache-control"], "no-store")

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

        notebooks = json.loads(server_app.list_notebooks().body.decode("utf-8"))
        self.assertEqual(notebooks["default_ids"], ["cmrc2018-demo"])
        self.assertEqual(notebooks["supported_extensions"], [".docx", ".md", ".pdf", ".txt"])

        result = retrieve(
            RequestContext("trace", "request"),
            "什么是静电感应？",
            server_app.vector_store,
            scope=["cmrc2018-demo"],
            top_k=3,
        )
        self.assertTrue(any("静电感应" in item.source_id for item in result.citations))

    def test_agent_receives_all_real_project_tools(self) -> None:
        names = [tool.name for tool in server_app.runtime.tool_definitions(RequestContext("t", "r"))]
        self.assertEqual(
            names,
            [
                "search_knowledge_base",
                "hybrid_search_knowledge_base",
                "keyword_search_knowledge_base",
                "list_knowledge_documents",
                "read_knowledge_document",
                "create_file",
                "save_conversation_to_knowledge_base",
            ],
        )

    def test_notebook_documents_lists_builtin_sources(self) -> None:
        payload = json.loads(
            server_app.notebook_documents("cmrc2018-demo").body.decode("utf-8")
        )
        self.assertEqual(payload["notebook_id"], "cmrc2018-demo")
        self.assertFalse(payload["writable"])
        self.assertEqual(len(payload["documents"]), 24)
        self.assertTrue(
            all(item["source_id"].startswith("cmrc2018-demo/") for item in payload["documents"])
        )
        self.assertTrue(all(item["chunks"] > 0 for item in payload["documents"]))

    def test_suggestions_come_from_the_selected_notebook(self) -> None:
        payload = json.loads(
            server_app.notebook_suggestions("cmrc2018-demo").body.decode("utf-8")
        )
        self.assertEqual(payload["notebook_id"], "cmrc2018-demo")
        self.assertEqual(payload["source"], "curated")
        self.assertEqual(len(payload["questions"]), 8)
        self.assertTrue(all(item["question"] for item in payload["questions"]))

    def test_topic_candidates_pick_chapters_over_plain_lines(self) -> None:
        # 用仓库内的 scratch 目录：系统临时目录在受限环境里可能不可写。
        scratch = ROOT / "data" / "_tests"
        scratch.mkdir(parents=True, exist_ok=True)
        suffix = tempfile._get_candidate_names().__next__()
        chaptered = scratch / f"chaptered-{suffix}.md"
        labelled = scratch / f"labelled-{suffix}.md"
        try:
            chaptered.write_text(
                "# 银河争霸战\n\n"
                "声明：本书为测试文本。\n\n"
                "第1章 彦清风\n\n正文内容。\n\n"
                "第2章 林古兰\n\n正文内容。\n",
                encoding="utf-8",
            )
            self.assertEqual(
                server_app._topic_candidates(chaptered, limit=2, skip="银河争霸战"),
                ["第1章 彦清风", "第2章 林古兰"],
            )

            labelled.write_text(
                "# 张志_中文简历\n\n张志\n\n个人简介\n\n曾任 C++ 后端。\n\n教育背景\n",
                encoding="utf-8",
            )
            self.assertEqual(
                server_app._topic_candidates(labelled, limit=4, skip="张志_中文简历"),
                ["个人简介", "教育背景"],
            )
        finally:
            chaptered.unlink(missing_ok=True)
            labelled.unlink(missing_ok=True)

    def test_same_content_is_not_imported_twice(self) -> None:
        notebook_dir = None
        try:
            notebook_dir, metadata = server_app._create_user_notebook("测试去重")
            content = "# 短文档\n\n只有一句话。\n"
            server_app._add_markdown_document(notebook_dir, metadata, "短文档.md", content)
            with self.assertRaisesRegex(ValueError, "已经导入过"):
                server_app._add_markdown_document(notebook_dir, metadata, "短文档.md", content)
        finally:
            if notebook_dir is not None:
                shutil.rmtree(notebook_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
