import pytest
from core_specifications import RequestContext
from data_facade import DataService


def test_source_delete_is_scoped_persistent_and_leaves_other_sources(tmp_path):
    ctx = RequestContext("delete", "request", "owner")
    database = str(tmp_path / "state.sqlite")
    data = DataService(database)
    store = data.vector_store(ctx)
    store.add("book/one", ["first", "second"], [[1.0], [1.0]])
    store.add("book/two", ["keep"], [[1.0]])
    store.add("other/one", ["private"], [[1.0]])
    with pytest.raises(ValueError):
        data.delete_document(ctx, "book", "other/one")
    data.delete_document(ctx, "book", "book/one")
    with pytest.raises(ValueError):
        data.delete_document(ctx, "book", "book/one")
    assert store.document_chunks("book/one") == []
    assert store.list_documents() == [("book/two", 1), ("other/one", 1)]
    assert {hit[0] for hit in store.search([1.0], scopes=["book"])} == {"book/two"}
    data.close(ctx)
    reopened = DataService(database)
    assert reopened.vector_store(ctx).document_chunks("book/one") == []
    reopened.close(ctx)
