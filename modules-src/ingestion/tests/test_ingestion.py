import os
import pathlib
import shutil
import unittest

from core_contracts import RequestContext
from ingestion import build_index, chunk, parse


class TestIngestion(unittest.TestCase):
    def test_chunk(self):
        out = chunk(["abcdefghij"], size=4, overlap=1)
        self.assertEqual(out, ["abcd", "defg", "ghij"])

    def test_parse_txt(self):
        d = pathlib.Path("data/_tests"); d.mkdir(parents=True, exist_ok=True)
        f = d / "kb.txt"
        f.write_text("第一段。\n\n第二段。", encoding="utf-8")
        self.addCleanup(lambda: shutil.rmtree(d, ignore_errors=True))
        self.assertEqual(len(parse(str(f))), 2)

    def test_build_index(self):
        d = pathlib.Path("data/_tests"); d.mkdir(parents=True, exist_ok=True)
        (d / "a.md").write_text("AAA。\n\nBBB。", encoding="utf-8")
        from rag_core import InMemoryVectorStore, embed

        store = InMemoryVectorStore()
        n = build_index(RequestContext("t", "r"), str(d), store, embed)
        self.assertGreaterEqual(n, 2)
        self.addCleanup(lambda: shutil.rmtree(d, ignore_errors=True))


if __name__ == "__main__":
    unittest.main()
