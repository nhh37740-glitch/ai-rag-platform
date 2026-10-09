import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core_specifications import RequestContext
from rag_core import (
    DEFAULT_READ_CHUNKS,
    InMemoryVectorStore,
    MAX_READ_CHUNKS,
    RagClient,
    VectorStore,
    document_info,
    embed,
    hybrid_search,
    keyword_search,
    list_documents,
    read_document,
    retrieve,
)


class TestRagCore(unittest.TestCase):
    def test_embed_retrieve(self):
        with patch.dict("os.environ", {"RAG_EMBED": "hash"}):
            store = InMemoryVectorStore()
            self.assertIsInstance(store, VectorStore)
            chunks = ["API 认证需要 Bearer token", "Bug 修复流程与 SOP", "网关 keep-alive 超时"]
            store.add("api-doc", chunks, embed(chunks))
            res = RagClient(store, top_k=2).retrieve(
                RequestContext("t", "r"),
                "API 如何认证？",
            )
        self.assertTrue(any("token" in c or "认证" in c for c in res.contexts))
        self.assertGreater(len(res.citations), 0)

    def test_retrieve_only_searches_selected_knowledge_base(self):
        with patch.dict("os.environ", {"RAG_EMBED": "hash"}):
            store = InMemoryVectorStore()
            first = ["产品知识：发布流程需要审批"]
            second = ["人事知识：年假申请需要审批"]
            store.add("product-notebook/release", first, embed(first))
            store.add("hr-notebook/leave", second, embed(second))
            result = retrieve(
                RequestContext("t", "r"),
                "审批",
                store,
                scope=["hr-notebook"],
                top_k=5,
            )
        self.assertEqual([item.metadata["knowledge_base_id"] for item in result.citations], ["hr-notebook"])

    def test_fastembed_is_the_default_backend(self):
        with patch.dict("os.environ", {}, clear=True):
            with patch("rag_core._embed_fastembed", return_value=[[1.0]]) as mocked:
                self.assertEqual(embed(["默认必须走模型"]), [[1.0]])
                mocked.assert_called_once_with(["默认必须走模型"])

    def test_unknown_backend_is_rejected(self):
        with patch.dict("os.environ", {"RAG_EMBED": "unknown"}):
            with self.assertRaisesRegex(ValueError, "RAG_EMBED"):
                embed(["测试"])


KB = "cmrc2018-demo"
OCCAM_CHUNK = "一个典型的归纳偏置例子是奥卡姆剃刀，它假设最简单而又一致的假设是最佳的。"
MEDAL_CHUNK = "海军十字勋章授予在战斗中表现英勇的军人。"


class TestKeywordSearch(unittest.TestCase):
    def _store(self) -> InMemoryVectorStore:
        store = InMemoryVectorStore()
        store.add(f"{KB}/006-归纳偏向", [OCCAM_CHUNK], [[0.0, 0.0]])
        store.add(f"{KB}/024-海军十字勋章", [MEDAL_CHUNK], [[0.0, 0.0]])
        return store

    def test_finds_exact_term_without_touching_the_embedding_model(self):
        store = self._store()
        with patch("rag_core.embed", side_effect=AssertionError("词面检索不得加载向量模型")) as mocked:
            result = keyword_search(RequestContext("t", "r"), "奥卡姆剃刀", store, scope=[KB], top_k=5)
        mocked.assert_not_called()
        self.assertEqual([item.source_id for item in result.citations], [f"{KB}/006-归纳偏向"])
        self.assertGreater(result.citations[0].score, 0.5)

    def test_returns_empty_result_when_nothing_matches(self):
        store = self._store()
        result = keyword_search(RequestContext("t", "r"), "量子纠缠", store, scope=[KB], top_k=5)
        self.assertEqual(result.contexts, [])
        self.assertEqual(result.citations, [])

    def test_rejects_invalid_arguments(self):
        store = self._store()
        with self.assertRaises(ValueError):
            keyword_search(RequestContext("t", "r"), "奥卡姆剃刀", store, top_k=0)
        with self.assertRaises(ValueError):
            keyword_search(RequestContext("t", "r"), "   ", store)


class TestHybridSearch(unittest.TestCase):
    def _store(self) -> InMemoryVectorStore:
        store = InMemoryVectorStore()
        store.add(f"{KB}/006-归纳偏向", [OCCAM_CHUNK], [[0.0, 1.0]])
        store.add(f"{KB}/024-海军十字勋章", [MEDAL_CHUNK], [[1.0, 0.0]])
        return store

    def test_keyword_match_outranks_the_vector_winner(self):
        store = self._store()
        ctx = RequestContext("t", "r")
        with patch("rag_core.embed", return_value=[[1.0, 0.0]]):
            vector_result = RagClient(
                store, embed_fn=lambda texts: [[1.0, 0.0]], top_k=2
            ).retrieve(ctx, "奥卡姆剃刀", scope=[KB])
            hybrid_result = hybrid_search(ctx, "奥卡姆剃刀", store, scope=[KB], top_k=2)
        self.assertEqual(vector_result.citations[0].source_id, f"{KB}/024-海军十字勋章")
        self.assertEqual(hybrid_result.citations[0].source_id, f"{KB}/006-归纳偏向")

    def test_rejects_invalid_alpha_and_top_k(self):
        store = self._store()
        ctx = RequestContext("t", "r")
        with self.assertRaises(ValueError):
            hybrid_search(ctx, "奥卡姆剃刀", store, alpha=1.0)
        with self.assertRaises(ValueError):
            hybrid_search(ctx, "奥卡姆剃刀", store, top_k=0)


class TestDocumentListing(unittest.TestCase):
    def _store(self) -> InMemoryVectorStore:
        store = InMemoryVectorStore()
        store.add(f"{KB}/b", ["一", "二"], [[0.0], [0.0]])
        store.add(f"{KB}/a", ["一"], [[0.0]])
        store.add("other-kb/c", ["一"], [[0.0]])
        return store

    def test_lists_documents_with_chunk_counts_and_scope(self):
        documents = list_documents(RequestContext("t", "r"), self._store(), scope=[KB])
        self.assertEqual([item["source_id"] for item in documents], [f"{KB}/a", f"{KB}/b"])
        self.assertEqual([item["chunk_count"] for item in documents], [1, 2])
        self.assertEqual(documents[0]["title"], "a")
        self.assertEqual(documents[0]["knowledge_base_id"], KB)

    def test_reads_whole_document_in_order(self):
        store = InMemoryVectorStore()
        store.add(f"{KB}/doc", ["第一段", "第二段", "第三段"], [[0.0], [0.0], [0.0]])
        result = read_document(RequestContext("t", "r"), store, f"{KB}/doc", max_chunks=2)
        self.assertEqual(result.contexts, ["第一段", "第二段"])
        self.assertEqual([item.score for item in result.citations], [1.0, 1.0])
        self.assertEqual(result.citations[0].source_id, f"{KB}/doc")

    def test_unknown_document_returns_empty_result(self):
        result = read_document(RequestContext("t", "r"), self._store(), f"{KB}/missing")
        self.assertEqual(result.contexts, [])
        self.assertEqual(result.citations, [])

    def test_read_document_rejects_invalid_input(self):
        store = self._store()
        with self.assertRaises(ValueError):
            read_document(RequestContext("t", "r"), store, f"{KB}/a", max_chunks=0)
        with self.assertRaises(ValueError):
            read_document(RequestContext("t", "r"), store, "   ")


class TestDocumentPaging(unittest.TestCase):
    def _store(self, chunk_count: int = 45) -> InMemoryVectorStore:
        store = InMemoryVectorStore()
        chunks = [f"第 {index} 块" for index in range(1, chunk_count + 1)]
        store.add(f"{KB}/long-doc", chunks, [[0.0]] * chunk_count)
        return store

    def test_document_info_reports_total_chunks(self):
        store = self._store()
        info = document_info(RequestContext("t", "r"), store, f"{KB}/long-doc")
        self.assertEqual(info["source_id"], f"{KB}/long-doc")
        self.assertEqual(info["title"], "long-doc")
        self.assertEqual(info["knowledge_base_id"], KB)
        self.assertEqual(info["chunk_count"], 45)

    def test_document_info_returns_zero_for_unknown_id(self):
        info = document_info(RequestContext("t", "r"), self._store(), f"{KB}/missing")
        self.assertEqual(info["chunk_count"], 0)

    def test_first_page_is_capped_at_the_default(self):
        result = read_document(RequestContext("t", "r"), self._store(), f"{KB}/long-doc")
        self.assertEqual(len(result.contexts), DEFAULT_READ_CHUNKS)
        self.assertEqual(result.contexts[0], "第 1 块")
        self.assertEqual(result.contexts[-1], f"第 {DEFAULT_READ_CHUNKS} 块")
        self.assertEqual(result.citations[0].metadata["chunk_index"], 1)
        self.assertEqual(result.citations[0].metadata["total_chunks"], 45)

    def test_offset_continues_where_the_previous_page_stopped(self):
        store = self._store()
        second_page = read_document(
            RequestContext("t", "r"), store, f"{KB}/long-doc", offset=DEFAULT_READ_CHUNKS
        )
        self.assertEqual(second_page.contexts[0], f"第 {DEFAULT_READ_CHUNKS + 1} 块")
        self.assertEqual(second_page.citations[0].metadata["chunk_index"], DEFAULT_READ_CHUNKS + 1)

    def test_one_call_can_never_return_the_whole_long_document(self):
        total_chunks = MAX_READ_CHUNKS * 3
        store = self._store(chunk_count=total_chunks)
        result = read_document(
            RequestContext("t", "r"), store, f"{KB}/long-doc", max_chunks=MAX_READ_CHUNKS
        )
        self.assertEqual(len(result.contexts), MAX_READ_CHUNKS)
        self.assertLess(len(result.contexts), total_chunks)
        self.assertEqual(result.citations[0].metadata["total_chunks"], total_chunks)

    def test_offset_beyond_the_end_returns_empty_result(self):
        result = read_document(RequestContext("t", "r"), self._store(), f"{KB}/long-doc", offset=999)
        self.assertEqual(result.contexts, [])
        self.assertEqual(result.citations, [])

    def test_invalid_paging_arguments_are_rejected(self):
        store = self._store()
        ctx = RequestContext("t", "r")
        with self.assertRaises(ValueError):
            read_document(ctx, store, f"{KB}/long-doc", max_chunks=0)
        with self.assertRaises(ValueError):
            read_document(ctx, store, f"{KB}/long-doc", max_chunks=MAX_READ_CHUNKS + 1)
        with self.assertRaises(ValueError):
            read_document(ctx, store, f"{KB}/long-doc", offset=-1)


if __name__ == "__main__":
    unittest.main()
