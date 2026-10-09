import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

from core_specifications import RequestContext, VectorStore
from memory import MemoryStore
from storage import SqliteVectorStore, StateStore, make_storage


CTX = RequestContext("t", "r", "user", "session")
OTHER = RequestContext("t2", "r2", "other", "session")


class TestSqliteVectorStore(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = str(Path(self.temporary.name) / "vectors.sqlite")
        self.store = SqliteVectorStore(self.path)
        self.addCleanup(self.store.close)

    def test_protocol_listing_scopes_chunks_and_order(self):
        self.assertIsInstance(self.store, VectorStore)
        self.store.add("alpha/a", ["first", "second"], [[1, 0], [0, 1]])
        self.store.add("beta/b", ["third"], [[0.5, 0.5]])
        self.assertEqual(self.store.list_documents(), [("alpha/a", 2), ("beta/b", 1)])
        self.assertEqual(self.store.list_documents(["alpha"]), [("alpha/a", 2)])
        self.assertEqual(self.store.document_chunks("alpha/a"), ["first", "second"])
        self.assertEqual(self.store.document_chunks("absent"), [])
        hits = self.store.search([1, 0])
        self.assertEqual(hits[0], ("alpha/a", "first", 1.0))
        self.assertEqual(self.store.search([1, 0], top_k=1, scopes=["beta"]), [("beta/b", "third", 0.5)])
        for scopes in ([], ["unknown"], ["alpha' OR 1=1 --"]):
            with self.subTest(scopes=scopes):
                self.assertEqual(self.store.search([1, 0], scopes=scopes), [])
                self.assertEqual(self.store.list_documents(scopes), [])
        self.assertEqual(self.store.document_chunks("alpha/a' OR 1=1 --"), [])

    def test_replacement_preserves_other_sources_and_reopen(self):
        self.store.add("alpha/a", ["old", "old2"], [[1, 0], [0, 1]])
        self.store.add("beta/b", ["other"], [[1, 1]])
        self.store.add("alpha/a", ["new"], [[0, 1]])
        self.assertEqual(self.store.list_documents(), [("alpha/a", 1), ("beta/b", 1)])
        self.store.close()
        reopened = SqliteVectorStore(self.path)
        self.addCleanup(reopened.close)
        self.assertEqual(reopened.document_chunks("alpha/a"), ["new"])
        self.assertEqual(reopened.document_chunks("beta/b"), ["other"])

    def test_invalid_replacement_does_not_destroy_data(self):
        self.store.add("alpha/a", ["original"], [[1, 0]])
        invalid = [
            (["replacement"], []),
            (["one", "two"], [[1, 0], [1]]),
            (["replacement"], [[]]),
            (["replacement"], [[float("nan"), 0]]),
            (["replacement"], [[float("inf"), 0]]),
            (["replacement"], [[[1, 0]]]),
            (["replacement"], [["not-a-number", 0]]),
            (["replacement"], [[1, 0, 0]]),
        ]
        for chunks, embeddings in invalid:
            with self.subTest(embeddings=embeddings):
                with self.assertRaises(ValueError):
                    self.store.add("alpha/a", chunks, embeddings)
                self.assertEqual(self.store.document_chunks("alpha/a"), ["original"])
                self.assertEqual(self.store.search([1, 0]), [("alpha/a", "original", 1.0)])

    def test_dimension_must_match_other_sources(self):
        self.store.add("alpha/a", ["first"], [[1, 0]])
        with self.assertRaises(ValueError):
            self.store.add("beta/b", ["wrong"], [[1, 0, 0]])
        self.assertEqual(self.store.list_documents(), [("alpha/a", 1)])
        with self.assertRaises(ValueError):
            self.store.search([1, 0, 0])

    def test_sql_error_rolls_back_replacement(self):
        self.store.add("alpha/a", ["original"], [[1, 0]])
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("CREATE TRIGGER reject_replacement BEFORE INSERT ON vectors "
                         "WHEN NEW.text = 'reject' BEGIN SELECT RAISE(ABORT, 'rejected'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.add("alpha/a", ["reject"], [[0, 1]])
        self.assertEqual(self.store.document_chunks("alpha/a"), ["original"])

    def test_empty_replacement_removes_only_its_source(self):
        self.store.add("alpha/a", ["one"], [[1, 0]])
        self.store.add("beta/b", ["two"], [[0, 1]])
        self.store.add("alpha/a", [], [])
        self.assertEqual(self.store.list_documents(), [("beta/b", 1)])

    def test_top_k_and_query_validation(self):
        for value, exception in ((True, TypeError), (1.5, TypeError), ("5", TypeError), (0, ValueError), (-1, ValueError)):
            with self.subTest(top_k=value), self.assertRaises(exception):
                self.store.search([1, 0], top_k=value)
        for query in ([], [float("nan")], [[1, 0]]):
            with self.subTest(query=query), self.assertRaises(ValueError):
                self.store.search(query)

    def test_atomic_parallel_replacements(self):
        def replace(index):
            self.store.add("alpha/a", [f"{index}:first", f"{index}:second"], [[1, 0], [0, 1]])
            self.store.search([1, 0])
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(replace, range(32)))
        chunks = self.store.document_chunks("alpha/a")
        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0].partition(":")[0], chunks[1].partition(":")[0])

    def test_existing_vectors_table_compatible(self):
        legacy_path = str(Path(self.temporary.name) / "legacy.sqlite")
        with closing(sqlite3.connect(legacy_path)) as conn, conn:
            conn.execute("CREATE TABLE vectors (source_id TEXT, text TEXT, embedding TEXT)")
            conn.execute("INSERT INTO vectors VALUES (?, ?, ?)", ("legacy/doc", "old text", "[1, 0]"))
        legacy = SqliteVectorStore(legacy_path)
        self.addCleanup(legacy.close)
        self.assertEqual(legacy.search([1, 0]), [("legacy/doc", "old text", 1.0)])
        legacy.add("legacy/doc", ["new text"], [[0, 1]])
        self.assertEqual(legacy.document_chunks("legacy/doc"), ["new text"])

    def test_close_rejects_all_operations(self):
        self.store.close()
        self.store.close()
        operations = [
            lambda: self.store.add("a", ["x"], [[1]]),
            lambda: self.store.search([1]),
            lambda: self.store.list_documents([]),
            lambda: self.store.document_chunks("a"),
        ]
        for operation in operations:
            with self.subTest(operation=operation), self.assertRaises(RuntimeError):
                operation()


class TestStateStore(unittest.TestCase):
    def setUp(self):
        self.store = StateStore(":memory:")
        self.addCleanup(self.store.close)

    def test_user_scope_json_copy_delete_and_parameterization(self):
        key = "prefs' OR 1=1 --"
        value = {"language": "中文", "items": [1, True, None]}
        self.assertIsNone(self.store.get(CTX, key))
        self.store.set(CTX, key, value)
        value["items"].append("mutated")
        self.assertEqual(self.store.get(CTX, key)["items"], [1, True, None])
        self.assertIsNone(self.store.get(OTHER, key))
        self.store.set(OTHER, key, ["other"])
        self.store.delete(CTX, key)
        self.assertIsNone(self.store.get(CTX, key))
        self.assertEqual(self.store.get(OTHER, key), ["other"])

    def test_invalid_json_does_not_replace_existing_value(self):
        self.store.set(CTX, "key", {"valid": True})
        for value, exception in ((object(), TypeError), (float("nan"), ValueError)):
            with self.subTest(value=value), self.assertRaises(exception):
                self.store.set(CTX, "key", value)
            self.assertEqual(self.store.get(CTX, "key"), {"valid": True})

    def test_close(self):
        self.store.close()
        self.store.close()
        for operation in (
            lambda: self.store.get(CTX, "key"),
            lambda: self.store.set(CTX, "key", 1),
            lambda: self.store.delete(CTX, "key"),
        ):
            with self.assertRaises(RuntimeError):
                operation()


class TestStorageCompatibility(unittest.TestCase):
    def test_unified_persistence(self):
        with tempfile.TemporaryDirectory() as directory:
            memory = MemoryStore(str(Path(directory) / "memory.sqlite"))
            vector = SqliteVectorStore(str(Path(directory) / "vectors.sqlite"))
            storage = make_storage(str(Path(directory) / "eval.sqlite"), memory, vector)
            try:
                storage.memory_write(CTX, "user", "project", "issue 网关 keep-alive")
                self.assertTrue(storage.memory_search(CTX, "user", "网关")[0].content)
                self.assertEqual(storage.memory_get(CTX, "user", "project").content, "issue 网关 keep-alive")
                storage.add_documents("api/doc", ["Bearer token"], [[1, 0]])
                self.assertEqual(storage.search_documents([1, 0])[0][0], "api/doc")
                storage.save_eval("run1", {"recall": 0.9})
                self.assertEqual(storage.load_eval("run1")["recall"], 0.9)
                storage.memory_forget(CTX, "user", "project")
                self.assertIsNone(storage.memory_get(CTX, "user", "project"))
                storage.close()
                with self.assertRaises(RuntimeError):
                    storage.load_eval("run1")
                # Injected stores are not closed by the legacy wrapper.
                self.assertEqual(vector.document_chunks("api/doc"), ["Bearer token"])
                self.assertIsNone(memory.get(CTX, "user", "project"))
            finally:
                storage.close()
                vector.close()
                memory.close()


if __name__ == "__main__":
    unittest.main()
