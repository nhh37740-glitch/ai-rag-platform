import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from core_specifications import RequestContext
from memory import make_memory


CTX = RequestContext("t", "r", "user1", "s1")
OTHER = RequestContext("t2", "r2", "user2", "s1")


class TestMemory(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = str(Path(self.temporary.name) / "memory.sqlite")
        self.memory = make_memory(self.path)
        self.addCleanup(self.memory.close)

    def test_write_get_search_forget(self):
        self.memory.write(CTX, "user", "project", "issue #1142 网关 keep-alive")
        self.assertEqual(self.memory.get(CTX, "user", "project").content, "issue #1142 网关 keep-alive")
        self.assertEqual(len(self.memory.search(CTX, "user", "issue 网关")), 1)
        self.memory.forget(CTX, "user", "project")
        self.assertIsNone(self.memory.get(CTX, "user", "project"))

    def test_replacement_and_user_isolation_persist(self):
        self.memory.write(CTX, "user", "project", "old")
        self.memory.write(CTX, "user", "project", "new")
        self.memory.write(OTHER, "user", "project", "other")
        self.assertEqual(len(self.memory.search(CTX, "user", "new")), 1)
        self.memory.close()
        reopened = make_memory(self.path)
        self.addCleanup(reopened.close)
        self.assertEqual(reopened.get(CTX, "user", "project").content, "new")
        self.assertEqual(reopened.get(OTHER, "user", "project").content, "other")

    def test_thread_safe_writes(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda number: self.memory.write(CTX, "user", "same", str(number)), range(32)))
        self.assertEqual(len(self.memory.search(CTX, "user", "")), 1)

    def test_validation_and_closed_guard(self):
        with self.assertRaises(ValueError):
            self.memory.get(None, "user", "key")
        for value, exception in ((True, TypeError), (0, ValueError)):
            with self.assertRaises(exception):
                self.memory.search(CTX, "user", "", value)
        self.memory.close()
        self.memory.close()
        for operation in (
            lambda: self.memory.get(CTX, "user", "key"),
            lambda: self.memory.write(CTX, "user", "key", "value"),
            lambda: self.memory.search(CTX, "user", "query"),
            lambda: self.memory.forget(CTX, "user", "key"),
        ):
            with self.assertRaises(RuntimeError):
                operation()


if __name__ == "__main__":
    unittest.main()
