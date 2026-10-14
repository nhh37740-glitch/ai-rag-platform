from unittest.mock import patch
import pytest
from core_specifications import RequestContext
from rag_facade import RagService


class Store:
    def __init__(self):
        self.sources = {}
    def add(self, source, chunks, embeddings):
        self.sources[source] = (chunks, embeddings)


def test_progress_reports_batches_before_atomic_commit(monkeypatch):
    monkeypatch.setenv("RAG_EMBED", "hash")
    store, events = Store(), []
    rag = RagService(store)
    def report(event):
        assert "book/source" not in store.sources
        events.append(dict(event))
    result = rag.ingest_markdown(RequestContext("t", "r"), "银河舰队" * 8000, "book/source", report)
    batches = [e for e in events if e["stage"] == "建立向量索引"]
    assert len(batches) > 2
    assert batches[0]["done"] == 0
    assert batches[-1]["done"] == result.chunk_count
    assert all(b["done"] - a["done"] <= 32 for a, b in zip(batches, batches[1:]))
    assert len(store.sources["book/source"][1]) == result.chunk_count


def test_embedding_failure_does_not_publish_partial_document():
    store = Store()
    rag = RagService(store)
    with patch("rag_facade.embed", side_effect=[[[1.0]] * 32, RuntimeError("inference failed")]):
        with pytest.raises(RuntimeError):
            rag.ingest_markdown(RequestContext("t", "r"), "银河舰队" * 8000, "book/source")
    assert store.sources == {}
