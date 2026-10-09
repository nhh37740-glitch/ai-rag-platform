import shutil
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from core_specifications import DataServicePort, MemoryStorePort, RequestContext, StateStorePort, VectorStore
from data_facade import DataService


CTX = RequestContext("trace", "request", "alice", "session")
OTHER = RequestContext("trace", "request", "bob", "session")


class TestDataService(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "nested" / "state"
        self.data = DataService(str(self.path))
        self.addCleanup(self.data.close, CTX)

    def test_D01_initialize_idempotent_and_store_identity(self):
        self.assertIsInstance(self.data, DataServicePort)
        self.data.initialize(CTX)
        first = (self.data.memory_store(CTX), self.data.vector_store(CTX), self.data.state_db(CTX))
        self.data.initialize(CTX)
        second = (self.data.memory_store(OTHER), self.data.vector_store(OTHER), self.data.state_db(OTHER))
        for previous, current in zip(first, second):
            self.assertIs(previous, current)
        for store, protocol in zip(first, (MemoryStorePort, VectorStore, StateStorePort)):
            self.assertIsInstance(store, protocol)
        for name in ("memory.sqlite", "vectors.sqlite", "state.sqlite"):
            self.assertTrue((self.path / name).is_file())

    def test_D02_persistence_after_reopen_and_user_state_isolation(self):
        self.data.memory_store(CTX).write(CTX, "user", "project", "中文项目")
        self.data.vector_store(CTX).add("kb/doc", ["first", "second"], [[1, 0], [0, 1]])
        self.data.state_db(CTX).set(CTX, "settings", {"theme": "dark"})
        self.data.state_db(OTHER).set(OTHER, "settings", {"theme": "light"})
        self.data.close(CTX)
        reopened = DataService(str(self.path))
        self.addCleanup(reopened.close, CTX)
        self.assertEqual(reopened.memory_store(CTX).get(CTX, "user", "project").content, "中文项目")
        self.assertEqual(reopened.vector_store(CTX).document_chunks("kb/doc"), ["first", "second"])
        self.assertEqual(reopened.state_db(CTX).get(CTX, "settings"), {"theme": "dark"})
        self.assertEqual(reopened.state_db(OTHER).get(OTHER, "settings"), {"theme": "light"})
        reopened.state_db(CTX).delete(CTX, "settings")
        self.assertIsNone(reopened.state_db(CTX).get(CTX, "settings"))
        self.assertEqual(reopened.state_db(OTHER).get(OTHER, "settings"), {"theme": "light"})

    def test_D03_atomic_same_source_replacement_invalid_add_preserves(self):
        store = self.data.vector_store(CTX)
        store.add("kb/doc", ["old", "old2"], [[1, 0], [0, 1]])
        store.add("kb/doc", ["new"], [[0, 1]])
        self.assertEqual(store.list_documents(), [("kb/doc", 1)])
        for chunks, embeddings in (
            (["bad"], []), (["bad"], [[float("nan"), 1]]),
            (["bad", "bad2"], [[1], [1, 0]]),
        ):
            with self.assertRaises(ValueError):
                store.add("kb/doc", chunks, embeddings)
            self.assertEqual(store.document_chunks("kb/doc"), ["new"])

    def test_D04_scopes_and_parameterized_keys(self):
        store = self.data.vector_store(CTX)
        store.add("kb/doc", ["public"], [[1, 0]])
        store.add("private/doc", ["private"], [[0, 1]])
        for scope in ([], ["missing"], ["kb' OR 1=1 --"]):
            self.assertEqual(store.list_documents(scope), [])
            self.assertEqual(store.search([1, 0], scopes=scope), [])
        self.assertEqual(store.list_documents(["kb"]), [("kb/doc", 1)])
        self.assertEqual(len(store.list_documents()), 2)
        state = self.data.state_db(CTX)
        state.set(CTX, "key' OR 1=1 --", {"value": "literal"})
        self.assertIsNone(state.get(OTHER, "key' OR 1=1 --"))
        self.assertEqual(state.get(CTX, "key' OR 1=1 --"), {"value": "literal"})

    def test_D05_close_is_idempotent_and_owned_stores_reject_access(self):
        memory, vector, state = self.data.memory_store(CTX), self.data.vector_store(CTX), self.data.state_db(CTX)
        self.data.close(CTX)
        self.data.close(CTX)
        for operation in (
            lambda: self.data.initialize(CTX), lambda: self.data.memory_store(CTX),
            lambda: self.data.vector_store(CTX), lambda: self.data.state_db(CTX),
            lambda: memory.write(CTX, "user", "k", "v"), lambda: memory.get(CTX, "user", "k"),
            lambda: memory.search(CTX, "user", ""), lambda: memory.forget(CTX, "user", "k"),
            lambda: vector.add("kb/doc", ["x"], [[1]]), lambda: vector.search([1]),
            lambda: vector.list_documents(), lambda: vector.document_chunks("kb/doc"),
            lambda: state.get(CTX, "key"), lambda: state.set(CTX, "key", 1),
            lambda: state.delete(CTX, "key"),
        ):
            with self.subTest(operation=operation), self.assertRaises(RuntimeError):
                operation()
        shutil.rmtree(self.path)
        self.assertFalse(self.path.exists())

    def test_memory_overrides_and_lazy_access(self):
        service = DataService(str(self.path), memory_db_path=":memory:", vector_db_path=":memory:")
        self.addCleanup(service.close, CTX)
        service.memory_store(CTX).write(CTX, "user", "key", "temporary")
        service.vector_store(CTX).add("kb/doc", ["temporary"], [[1]])
        self.assertFalse((self.path / "memory.sqlite").exists())
        self.assertFalse((self.path / "vectors.sqlite").exists())
        self.assertTrue((self.path / "state.sqlite").exists())

    def test_parallel_initialization_returns_one_store(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            stores = list(pool.map(lambda number: self.data.vector_store(CTX), range(32)))
        self.assertTrue(all(store is stores[0] for store in stores))

    def test_failed_initialize_is_retryable_and_releases_connections(self):
        invalid = self.path / "blocked"
        invalid.mkdir(parents=True)
        service = DataService(str(self.path), vector_db_path=str(invalid))
        self.addCleanup(service.close, CTX)
        with self.assertRaises(Exception):
            service.initialize(CTX)
        # The memory connection created before the vector failure must be released.
        (self.path / "memory.sqlite").unlink()
        invalid.rmdir()
        service.initialize(CTX)
        self.assertTrue(service.vector_store(CTX) is service.vector_store(CTX))

    def test_close_before_initialize(self):
        self.data.close(CTX)
        self.data.close(CTX)
        self.assertFalse(self.path.exists())
        with self.assertRaises(RuntimeError):
            self.data.initialize(CTX)


if __name__ == "__main__":
    unittest.main()
