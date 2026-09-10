import unittest

from core_contracts import RequestContext
from rag_core import InMemoryVectorStore, embed, retrieve


class TestRagCore(unittest.TestCase):
    def test_embed_retrieve(self):
        store = InMemoryVectorStore()
        chunks = ["API 认证需要 Bearer token", "Bug 修复流程与 SOP", "网关 keep-alive 超时"]
        store.add("api-doc", chunks, embed(chunks))
        res = retrieve(RequestContext("t", "r"), "API 如何认证？", store, top_k=2)
        self.assertTrue(any("token" in c or "认证" in c for c in res.contexts))
        self.assertGreater(len(res.citations), 0)

    def test_retrieve_only_searches_selected_knowledge_base(self):
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


if __name__ == "__main__":
    unittest.main()
