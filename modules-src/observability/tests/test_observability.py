import unittest

from core_specifications import RequestContext
from observability import TraceStore, Span, make_trace_store


class TestObservability(unittest.TestCase):
    def test_span_records(self):
        store = make_trace_store()
        ctx = RequestContext("t1", "r1", "u1", "s1")
        with Span(ctx, "llm", store) as s:
            pass
        events = store.get("t1")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].span, "llm")
        self.assertEqual(events[0].status, "ok")

    def test_get_empty(self):
        store = TraceStore()
        self.assertEqual(store.get("nope"), [])


if __name__ == "__main__":
    unittest.main()
