import unittest
from unittest.mock import patch

from core_contracts import RequestContext
from rag_core import InMemoryVectorStore, RagClient, VectorStore, embed, retrieve


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


if __name__ == "__main__":
    unittest.main()
