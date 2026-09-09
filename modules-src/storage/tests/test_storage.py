import pathlib
import shutil
import unittest

from core_contracts import RequestContext
from memory import make_memory
from rag_core import InMemoryVectorStore, embed
from storage import make_storage


class TestStorage(unittest.TestCase):
    def test_unified_persistence(self):
        d = pathlib.Path("data/_tests"); d.mkdir(parents=True, exist_ok=True)
        db = d / "storage.db"
        self.addCleanup(lambda: shutil.rmtree(d, ignore_errors=True))
        s = make_storage(str(db), make_memory(str(db)), InMemoryVectorStore())
        ctx = RequestContext("t", "r", "u", "s")
        s.memory_write(ctx, "user", "project", "issue #1142 网关 keep-alive")
        self.assertTrue(s.memory_search(ctx, "user", "网关")[0].content)
        chunks = ["API 认证需要 Bearer token"]
        s.add_documents("api", chunks, embed(chunks))
        self.assertEqual(s.search_documents(embed(["API 认证"])[0])[0][0], "api")
        s.save_eval("run1", {"recall": 0.9})
        self.assertEqual(s.load_eval("run1")["recall"], 0.9)


if __name__ == "__main__":
    unittest.main()
