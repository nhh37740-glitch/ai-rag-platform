import os
import pathlib
import shutil
import unittest
import uuid

from core_contracts import RequestContext
from memory import make_memory


class TestMemory(unittest.TestCase):
    def test_write_get_search(self):
        d = pathlib.Path("data/_tests"); d.mkdir(parents=True, exist_ok=True)
        db = d / ("m" + uuid.uuid4().hex[:8] + ".db")
        self.addCleanup(lambda: shutil.rmtree(d, ignore_errors=True))
        mem = make_memory(str(db))
        ctx = RequestContext("t", "r", "user1", "s1")
        mem.write(ctx, "user", "project", "在排查 issue #1142 网关 keep-alive")
        got = mem.get(ctx, "user", "project")
        self.assertIsNotNone(got)
        hits = mem.search(ctx, "user", "issue 网关")
        self.assertGreaterEqual(len(hits), 1)
        mem.forget(ctx, "user", "project")
        self.assertIsNone(mem.get(ctx, "user", "project"))


if __name__ == "__main__":
    unittest.main()
