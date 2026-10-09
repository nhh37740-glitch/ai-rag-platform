import json
import unittest
from unittest.mock import patch

from core_specifications import Citation, RequestContext, RetrievalResult
from rag_core import DEFAULT_READ_CHUNKS, MAX_READ_CHUNKS
from rag_tools import MAX_TOP_K, RagTools


KB = "cmrc2018-demo"
OCCAM_SOURCE = f"{KB}/006-归纳偏向"


class RecordingTraceStore:
    def __init__(self):
        self.events = []

    def record(self, span):
        self.events.append(span)


def _result(query: str) -> RetrievalResult:
    text = "一个典型的归纳偏置例子是奥卡姆剃刀，它假设最简单而又一致的假设是最佳的。"
    return RetrievalResult(
        query=query,
        contexts=[text],
        citations=[
            Citation(
                source_id=OCCAM_SOURCE,
                title="006-归纳偏向",
                text=text,
                score=0.91,
                metadata={"knowledge_base_id": KB},
            )
        ],
    )


class TestRagTools(unittest.TestCase):
    def setUp(self):
        self.store = object()
        self.tracing = RecordingTraceStore()
        self.rag_tools = RagTools(self.store, self.tracing)
        self.ctx = RequestContext("trace-1", "request-1")

    # ---------------------------------------------------------------- 工具定义

    def test_tool_definitions_cover_all_five_tools(self):
        definitions = self.rag_tools.tool_definitions()
        self.assertEqual(
            [item.name for item in definitions],
            [
                "search_knowledge_base",
                "hybrid_search_knowledge_base",
                "keyword_search_knowledge_base",
                "list_knowledge_documents",
                "read_knowledge_document",
            ],
        )
        for definition in definitions:
            self.assertIs(definition.parameters["additionalProperties"], False)
            self.assertNotIn("knowledge_base_ids", definition.parameters["properties"])
        self.assertEqual(
            definitions[0].parameters["required"],
            ["query"],
        )
        self.assertEqual(
            definitions[3].parameters["required"],
            [],
        )
        self.assertEqual(
            definitions[4].parameters["required"],
            ["source_id"],
        )
        self.assertEqual(
            definitions[1].parameters["properties"]["top_k"]["maximum"],
            MAX_TOP_K,
        )

    # ---------------------------------------------------------------- 检索类工具

    @patch("rag_tools.retrieve")
    def test_search_uses_only_injected_scope_and_returns_json(self, mocked_retrieve):
        mocked_retrieve.return_value = _result("奥卡姆剃刀")

        payload = json.loads(
            self.rag_tools.search(
                self.ctx, "奥卡姆剃刀", [KB, KB], top_k=3
            )
        )

        mocked_retrieve.assert_called_once_with(
            self.ctx, "奥卡姆剃刀", self.store, scope=[KB], top_k=3
        )
        self.assertEqual(payload["tool"], "search_knowledge_base")
        self.assertEqual(payload["hit_count"], 1)
        self.assertEqual(payload["citations"][0]["title"], "006-归纳偏向")
        self.assertEqual(len(self.tracing.events), 1)
        self.assertEqual(self.tracing.events[0].span, "rag")
        self.assertEqual(self.tracing.events[0].status, "ok")
        self.assertEqual(self.tracing.events[0].meta["tool"], "search_knowledge_base")
        self.assertEqual(self.tracing.events[0].meta["hits"][0]["rank"], 1)

    @patch("rag_tools.run_hybrid_search")
    def test_hybrid_search_routes_to_rag_core(self, mocked_hybrid):
        mocked_hybrid.return_value = _result("奥卡姆剃刀")

        payload = json.loads(self.rag_tools.hybrid_search(self.ctx, "奥卡姆剃刀", [KB]))

        mocked_hybrid.assert_called_once_with(
            self.ctx, "奥卡姆剃刀", self.store, scope=[KB], top_k=5
        )
        self.assertEqual(payload["tool"], "hybrid_search_knowledge_base")
        self.assertEqual(self.tracing.events[0].meta["tool"], "hybrid_search_knowledge_base")

    @patch("rag_tools.run_keyword_search")
    def test_keyword_search_routes_to_rag_core(self, mocked_keyword):
        mocked_keyword.return_value = _result("奥卡姆剃刀")

        payload = json.loads(self.rag_tools.keyword_search(self.ctx, "奥卡姆剃刀", [KB], top_k=2))

        mocked_keyword.assert_called_once_with(
            self.ctx, "奥卡姆剃刀", self.store, scope=[KB], top_k=2
        )
        self.assertEqual(payload["tool"], "keyword_search_knowledge_base")

    def test_invalid_top_k_is_traced_as_an_error(self):
        with self.assertRaises(ValueError):
            self.rag_tools.keyword_search(self.ctx, "问题", [KB], top_k=MAX_TOP_K + 1)

        self.assertEqual(len(self.tracing.events), 1)
        self.assertEqual(self.tracing.events[0].status, "error")
        self.assertEqual(self.tracing.events[0].meta["knowledge_base_ids"], [KB])

    # ---------------------------------------------------------------- 列目录

    @patch("rag_tools.run_list_documents")
    def test_list_documents_returns_catalogue(self, mocked_list):
        mocked_list.return_value = [
            {
                "source_id": OCCAM_SOURCE,
                "title": "006-归纳偏向",
                "knowledge_base_id": KB,
                "chunk_count": 3,
            }
        ]

        payload = json.loads(self.rag_tools.list_documents(self.ctx, [KB]))

        mocked_list.assert_called_once_with(self.ctx, self.store, scope=[KB])
        self.assertEqual(payload["tool"], "list_knowledge_documents")
        self.assertEqual(payload["document_count"], 1)
        self.assertEqual(payload["documents"][0]["source_id"], OCCAM_SOURCE)
        self.assertEqual(self.tracing.events[0].meta["hit_count"], 1)
        self.assertEqual(self.tracing.events[0].meta["query"], "")

    # ---------------------------------------------------------------- 读全文

    def _page(self, offset: int, returned: int, total: int) -> RetrievalResult:
        contexts = [f"第 {index} 块" for index in range(offset + 1, offset + returned + 1)]
        return RetrievalResult(
            query=OCCAM_SOURCE,
            contexts=contexts,
            citations=[
                Citation(
                    source_id=OCCAM_SOURCE,
                    title="006-归纳偏向",
                    text=text,
                    score=1.0,
                    metadata={
                        "knowledge_base_id": KB,
                        "chunk_index": offset + position,
                        "total_chunks": total,
                    },
                )
                for position, text in enumerate(contexts, start=1)
            ],
        )

    @patch("rag_tools.run_read_document")
    @patch("rag_tools.run_document_info")
    def test_read_document_returns_a_truncated_page_with_a_cursor(
        self, mocked_info, mocked_read
    ):
        mocked_info.return_value = {"source_id": OCCAM_SOURCE, "chunk_count": 34}
        mocked_read.return_value = self._page(0, DEFAULT_READ_CHUNKS, 34)

        payload = json.loads(self.rag_tools.read_document(self.ctx, OCCAM_SOURCE, [KB]))

        mocked_read.assert_called_once_with(
            self.ctx, self.store, OCCAM_SOURCE, max_chunks=DEFAULT_READ_CHUNKS, offset=0
        )
        self.assertEqual(payload["tool"], "read_knowledge_document")
        self.assertEqual(payload["source_id"], OCCAM_SOURCE)
        self.assertEqual(payload["offset"], 0)
        self.assertEqual(payload["max_chunks"], DEFAULT_READ_CHUNKS)
        self.assertEqual(payload["returned_chunks"], DEFAULT_READ_CHUNKS)
        self.assertEqual(payload["total_chunks"], 34)
        self.assertTrue(payload["truncated"])
        self.assertEqual(payload["next_offset"], DEFAULT_READ_CHUNKS)
        self.assertEqual(payload["hit_count"], DEFAULT_READ_CHUNKS)

        meta = self.tracing.events[0].meta
        self.assertTrue(meta["truncated"])
        self.assertEqual(meta["offset"], 0)
        self.assertEqual(meta["max_chunks"], DEFAULT_READ_CHUNKS)
        self.assertEqual(self.tracing.events[0].status, "ok")

    @patch("rag_tools.run_read_document")
    @patch("rag_tools.run_document_info")
    def test_last_page_is_not_truncated(self, mocked_info, mocked_read):
        mocked_info.return_value = {"source_id": OCCAM_SOURCE, "chunk_count": 34}
        mocked_read.return_value = self._page(20, 14, 34)

        payload = json.loads(
            self.rag_tools.read_document(self.ctx, OCCAM_SOURCE, [KB], offset=20)
        )

        self.assertEqual(payload["returned_chunks"], 14)
        self.assertFalse(payload["truncated"])
        self.assertIsNone(payload["next_offset"])

    @patch("rag_tools.run_read_document")
    @patch("rag_tools.run_document_info")
    def test_max_chunks_override_is_passed_through(self, mocked_info, mocked_read):
        mocked_info.return_value = {"source_id": OCCAM_SOURCE, "chunk_count": 34}
        mocked_read.return_value = self._page(0, 5, 34)

        payload = json.loads(
            self.rag_tools.read_document(self.ctx, OCCAM_SOURCE, [KB], max_chunks=5)
        )

        mocked_read.assert_called_once_with(
            self.ctx, self.store, OCCAM_SOURCE, max_chunks=5, offset=0
        )
        self.assertEqual(payload["max_chunks"], 5)
        self.assertEqual(payload["next_offset"], 5)

    def test_read_document_rejects_invalid_paging_arguments(self):
        with self.assertRaises(ValueError):
            self.rag_tools.read_document(self.ctx, OCCAM_SOURCE, [KB], max_chunks=MAX_READ_CHUNKS + 1)
        with self.assertRaises(ValueError):
            self.rag_tools.read_document(self.ctx, OCCAM_SOURCE, [KB], max_chunks=0)
        with self.assertRaises(ValueError):
            self.rag_tools.read_document(self.ctx, OCCAM_SOURCE, [KB], offset=-1)
        self.assertTrue(all(event.status == "error" for event in self.tracing.events))

    @patch("rag_tools.run_read_document")
    @patch("rag_tools.run_document_info")
    def test_read_document_rejects_source_outside_scope(self, mocked_info, mocked_read):
        with self.assertRaisesRegex(ValueError, "不在当前知识库范围内"):
            self.rag_tools.read_document(self.ctx, "other-kb/secret", [KB])

        mocked_info.assert_not_called()
        mocked_read.assert_not_called()
        self.assertEqual(len(self.tracing.events), 1)
        self.assertEqual(self.tracing.events[0].status, "error")
        self.assertEqual(self.tracing.events[0].meta["knowledge_base_ids"], [KB])

    def test_read_document_rejects_blank_source_id(self):
        with self.assertRaises(ValueError):
            self.rag_tools.read_document(self.ctx, "   ", [KB])
        self.assertEqual(self.tracing.events[0].status, "error")

    # ---------------------------------------------------------------- 范围注入

    def test_scope_must_be_a_list_of_strings(self):
        with self.assertRaises(TypeError):
            self.rag_tools.search(self.ctx, "问题", KB)  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            self.rag_tools.search(self.ctx, "问题", ["  "])


if __name__ == "__main__":
    unittest.main()
