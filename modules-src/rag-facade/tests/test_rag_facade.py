import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from core_specifications import (
    IngestResult, RagServicePort, RequestContext, RetrievalResult, ToolCall, VectorStore,
)
from rag_facade import RagService
from rag_tools import RagTools


class FakeVectorStore:
    """Protocol-only store, deliberately unrelated to a persistence implementation."""

    def __init__(self):
        self.documents = {}
        self.vectors = {}
        self.search_scopes = []

    def add(self, source_id, chunks, embeddings):
        self.documents[source_id] = list(chunks)
        self.vectors[source_id] = [list(vector) for vector in embeddings]

    def search(self, embedding, top_k=5, scopes=None):
        self.search_scopes.append(scopes)
        hits = [
            (source_id, text, sum(a * b for a, b in zip(embedding, vector)))
            for source_id, texts in self.documents.items()
            if scopes is None or source_id.partition("/")[0] in scopes
            for text, vector in zip(texts, self.vectors[source_id])
        ]
        return sorted(hits, key=lambda hit: -hit[2])[:top_k]

    def list_documents(self, scopes=None):
        return sorted((source_id, len(texts)) for source_id, texts in self.documents.items()
                      if scopes is None or source_id.partition("/")[0] in scopes)

    def document_chunks(self, source_id):
        return list(self.documents.get(source_id, []))


class RecordingTraceStore:
    def __init__(self):
        self.events = []

    def record(self, span):
        self.events.append(span)

    def get(self, trace_id):
        return [event for event in self.events if event.trace_id == trace_id]


class TestRagFacade(unittest.TestCase):
    def setUp(self):
        self.backend = patch.dict(os.environ, {"RAG_EMBED": "hash"})
        self.backend.start()
        self.addCleanup(self.backend.stop)
        self.store = FakeVectorStore()
        self.trace = RecordingTraceStore()
        self.ctx = RequestContext("trace-rag", "request-rag", "user-rag", "session-rag")
        self.rag = RagService(self.store, self.trace)

    def _seed(self):
        self.rag.ingest_markdown(self.ctx, "SQLite memory persist\n\n原子替换向量", "selected/guide")
        self.rag.ingest_markdown(self.ctx, "SQLite secret excluded", "excluded/secret")
        self.trace.events.clear()

    def test_R01_empty_unknown_and_explicit_empty_scope(self):
        self.assertIsInstance(self.store, VectorStore)
        self.assertIsInstance(self.rag, RagServicePort)
        for mode in ("vector", "hybrid", "keyword"):
            with self.subTest(mode=mode):
                empty = self.rag.search(self.ctx, "SQLite", ["missing"], mode=mode)
                self.assertIsInstance(empty, RetrievalResult)
                self.assertEqual(empty.citations, [])
        self._seed()
        for mode in ("vector", "hybrid", "keyword"):
            # Unavailable model is irrelevant when there is no selected knowledge base.
            with patch.dict(os.environ, {"RAG_EMBED": "unsupported"}):
                result = self.rag.search(self.ctx, "SQLite", [], mode=mode)
            self.assertEqual(result.contexts, [])
        self.assertEqual(self.rag.list_documents(self.ctx, []), [])
        self.assertEqual(self.rag.list_documents(self.ctx, ["missing"]), [])

    def test_R02_import_markdown_text_and_docx(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "manual.md").write_text("# SQLite\n\nSQLite is persistent memory.", encoding="utf-8")
            (root / "manual.txt").write_text("SQLite persistent memory.", encoding="utf-8")
            with zipfile.ZipFile(root / "manual.docx", "w") as document:
                document.writestr("word/document.xml", (
                    '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                    '<w:body><w:p><w:r><w:t>SQLite persistent memory.</w:t></w:r></w:p></w:body>'
                    '</w:document>'
                ))
            for extension in ("md", "txt", "docx"):
                with self.subTest(extension=extension):
                    source_id = f"selected/{extension}"
                    result = self.rag.ingest(self.ctx, str(root / f"manual.{extension}"), "selected", source_id)
                    self.assertIsInstance(result, IngestResult)
                    self.assertEqual(result.source_id, source_id)
                    self.assertEqual(result.knowledge_base_id, "selected")
                    self.assertEqual(result.chunk_count, len(self.store.document_chunks(source_id)))
                    read = self.rag.read_document(self.ctx, source_id, ["selected"])
                    self.assertEqual(len(read.citations), result.chunk_count)
                    self.assertTrue(all(c.source_id == source_id for c in read.citations))
            documents = self.rag.list_documents(self.ctx, ["selected"])
            self.assertEqual(len(documents), 3)
            for mode in ("vector", "hybrid", "keyword"):
                found = self.rag.search(self.ctx, "SQLite", ["selected"], mode=mode)
                self.assertTrue(found.citations)
                self.assertTrue(all(c.source_id.startswith("selected/") for c in found.citations))

    def test_R03_top_k_and_query_validation(self):
        for limit, error in ((0, ValueError), (21, ValueError), (True, TypeError), (1.5, TypeError)):
            with self.subTest(limit=limit):
                with self.assertRaises(error):
                    RagService(self.store, self.trace, limit)
                for mode in ("vector", "hybrid", "keyword"):
                    with self.assertRaises(error):
                        self.rag.search(self.ctx, "SQLite", [], top_k=limit, mode=mode)
        for query in ("", "  ", "\n"):
            with self.assertRaises(ValueError):
                self.rag.search(self.ctx, query, [])
        with self.assertRaises(TypeError):
            self.rag.search(self.ctx, 12, [])
        for mode in ("invalid", None, [], 1):
            with self.assertRaises(ValueError):
                self.rag.search(self.ctx, "SQLite", [], mode=mode)

    def test_scope_must_be_explicit_and_cannot_traverse(self):
        for scopes, error in ((None, TypeError), ("selected", TypeError), ([True], TypeError),
                              ([""], ValueError), (["../selected"], ValueError), (["a/b"], ValueError)):
            with self.subTest(scopes=scopes):
                with self.assertRaises(error):
                    self.rag.search(self.ctx, "SQLite", scopes)
        self._seed()
        docs = self.rag.list_documents(self.ctx, [" selected ", "selected"])
        self.assertEqual([doc["source_id"] for doc in docs], ["selected/guide"])

    def test_R04_scope_and_source_validation(self):
        self._seed()
        for source_id in ("excluded/secret", "selected/../guide", "../guide", "selected/..",
                          "selected\\guide", "/selected/guide", "selected/", "selected/guide/more"):
            with self.subTest(source=source_id):
                with self.assertRaises(ValueError):
                    self.rag.read_document(self.ctx, source_id, ["selected"])
        with self.assertRaises(ValueError):
            self.rag.read_document(self.ctx, "selected/guide", [])
        empty = self.rag.read_document(self.ctx, "missing/document", ["missing"])
        self.assertEqual(empty.citations, [])

    def test_R04_page_offsets_limits_and_metadata(self):
        chunks = [f"chunk {i}" for i in range(125)]
        self.store.add("selected/long", chunks, [[1.0]] * len(chunks))
        first = self.rag.read_document(self.ctx, "selected/long", ["selected"])
        self.assertEqual(first.contexts, chunks[:20])
        self.assertEqual(first.citations[0].metadata["chunk_index"], 1)
        self.assertEqual(first.citations[-1].metadata["total_chunks"], 125)
        second = self.rag.read_document(self.ctx, "selected/long", ["selected"], offset=20, max_chunks=100)
        self.assertEqual(second.contexts, chunks[20:120])
        call = ToolCall("read", "read_knowledge_document", {"source_id": "selected/long", "offset": 120})
        tail = json.loads(self.rag.execute_tool(self.ctx, call, ["selected"]))
        self.assertEqual(tail["returned_chunks"], 5)
        self.assertEqual(tail["total_chunks"], 125)
        self.assertFalse(tail["truncated"])
        self.assertIsNone(tail["next_offset"])
        self.assertEqual(self.rag.read_document(self.ctx, "selected/long", ["selected"], offset=150).citations, [])
        for offset, error in ((-1, ValueError), (True, TypeError), (0.5, TypeError)):
            with self.assertRaises(error):
                self.rag.read_document(self.ctx, "selected/long", ["selected"], offset=offset)
        for limit, error in ((0, ValueError), (101, ValueError), (True, TypeError), ("20", TypeError)):
            with self.assertRaises(error):
                self.rag.read_document(self.ctx, "selected/long", ["selected"], max_chunks=limit)

    def test_R05_five_tools_keep_exact_leaf_payload_and_trace(self):
        self._seed()
        leaf = RagTools(self.store, RecordingTraceStore())
        cases = [
            ("search_knowledge_base", {"query": "SQLite"}, lambda: leaf.search(self.ctx, "SQLite", ["selected"])),
            ("hybrid_search_knowledge_base", {"query": "SQLite"}, lambda: leaf.hybrid_search(self.ctx, "SQLite", ["selected"])),
            ("keyword_search_knowledge_base", {"query": "SQLite"}, lambda: leaf.keyword_search(self.ctx, "SQLite", ["selected"])),
            ("list_knowledge_documents", {}, lambda: leaf.list_documents(self.ctx, ["selected"])),
            ("read_knowledge_document", {"source_id": "selected/guide"}, lambda: leaf.read_document(self.ctx, "selected/guide", ["selected"])),
        ]
        self.assertEqual([definition.name for definition in self.rag.tool_definitions(self.ctx)], [name for name, _, _ in cases])
        for name, arguments, expected in cases:
            with self.subTest(tool=name):
                spoofed = {**arguments, "knowledge_base_ids": ["excluded"], "ctx": "model-context",
                           "runtime_context": {"knowledge_base_ids": ["excluded"]}}
                call = ToolCall("call", name, spoofed)
                actual = json.loads(self.rag.execute_tool(self.ctx, call, ["selected"]))
                self.assertEqual(actual, json.loads(expected()))
                self.assertEqual(call.arguments, spoofed)
                event = self.trace.events[-1]
                self.assertEqual(event.trace_id, self.ctx.trace_id)
                self.assertEqual(event.span, "rag")
                self.assertEqual(event.meta["tool"], name)
                self.assertEqual(event.meta["knowledge_base_ids"], ["selected"])
                self.assertTrue(all(hit["source_id"].startswith("selected/") for hit in event.meta["hits"]))

    def test_tool_unknown_bad_arguments_and_failures_record_error(self):
        for name, arguments, error in (
            ("invented", {}, ValueError), ("search_knowledge_base", {}, TypeError),
            ("search_knowledge_base", {"query": "  "}, ValueError),
            ("list_knowledge_documents", {"extra": True}, ValueError),
            ("list_knowledge_documents", [], TypeError),
            ("read_knowledge_document", {"source_id": "excluded/secret"}, ValueError),
        ):
            with self.subTest(tool=name, arguments=arguments):
                with self.assertRaises(error):
                    self.rag.execute_tool(self.ctx, ToolCall("call", name, arguments), ["selected"])
                event = self.trace.events[-1]
                self.assertEqual(event.status, "error")
                self.assertEqual(event.meta["tool"], name)
                self.assertEqual(event.trace_id, self.ctx.trace_id)
        self._seed()
        with patch.object(self.store, "search", side_effect=RuntimeError("store failed")):
            with self.assertRaisesRegex(RuntimeError, "store failed"):
                self.rag.search(self.ctx, "SQLite", ["selected"])
        self.assertEqual(self.trace.events[-1].status, "error")

    def test_typed_retrieval_records_actual_scope_and_hits(self):
        self._seed()
        self.rag.search(self.ctx, "SQLite", ["selected"], mode="keyword")
        self.rag.list_documents(self.ctx, ["selected"])
        self.rag.read_document(self.ctx, "selected/guide", ["selected"])
        self.assertEqual(len(self.trace.events), 3)
        self.assertTrue(all(event.status == "ok" and event.trace_id == self.ctx.trace_id for event in self.trace.events))
        for event in self.trace.events:
            self.assertEqual(event.meta["knowledge_base_ids"], ["selected"])
            self.assertGreaterEqual(event.end_ns, event.start_ns)
            self.assertTrue(event.meta["hit_count"])

    def test_ingestion_invalid_empty_and_mismatched_inputs_leave_store_untouched(self):
        for source in ("", "kb", "../document", "kb/../document", "kb/..", "kb/a/b", "kb\\a", "kb/a:b"):
            with self.subTest(source=source):
                with self.assertRaises(ValueError):
                    self.rag.ingest_markdown(self.ctx, "body", source)
        with self.assertRaises(ValueError):
            self.rag.ingest_markdown(self.ctx, " \n\t", "kb/doc")
        with self.assertRaises(ValueError):
            self.rag.ingest(self.ctx, "missing.md", "kb", "other/doc")
        with self.assertRaises(TypeError):
            self.rag.ingest(self.ctx, "missing.md", "kb", False)
        with self.assertRaises(ValueError):
            self.rag.ingest(self.ctx, "  ", "kb")
        with tempfile.TemporaryDirectory() as temporary:
            for extension in ("md", "txt"):
                path = Path(temporary) / f"empty.{extension}"
                path.write_text(" \n", encoding="utf-8")
                with self.assertRaises(ValueError):
                    self.rag.ingest(self.ctx, str(path), "kb")
            path = Path(temporary) / "bad.csv"
            path.write_text("x,y", encoding="utf-8")
            with self.assertRaises(ValueError):
                self.rag.parse_document(self.ctx, str(path))
        self.assertEqual(self.store.documents, {})

    def test_ingestion_default_source_split_embed_and_replacement(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "manual.md"
            path.write_text("# First\n\n" + "SQLite " * 200, encoding="utf-8")
            first = self.rag.ingest(self.ctx, str(path), "selected")
            self.assertEqual(first.source_id, "selected/manual")
            self.assertGreater(first.chunk_count, 1)
            path.write_text("# Replaced", encoding="utf-8")
            second = self.rag.ingest(self.ctx, str(path), "selected")
            self.assertEqual(second.chunk_count, 1)
            self.assertEqual(self.rag.read_document(self.ctx, second.source_id, ["selected"]).contexts, ["# Replaced"])
        self.assertEqual(self.rag.embed_texts(self.ctx, []), [])
        self.assertEqual(len(self.rag.embed_texts(self.ctx, ["SQLite"])), 1)
        with self.assertRaises(ValueError):
            self.rag.embed_texts(self.ctx, ["  "])
        with self.assertRaises(TypeError):
            self.rag.split_text(self.ctx, 1)


if __name__ == "__main__":
    unittest.main()
