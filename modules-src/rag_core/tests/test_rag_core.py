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


if __name__ == "__main__":
    unittest.main()
