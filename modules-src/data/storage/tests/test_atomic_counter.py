import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from core_specifications import RequestContext
from storage import StateStore


class AtomicCounterTests(unittest.TestCase):
    def test_independent_connections_reserve_at_most_twenty_and_persist(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "state.sqlite")
            ctx = RequestContext("trace", "request", "site")
            stores = [StateStore(path) for _ in range(8)]
            try:
                with ThreadPoolExecutor(max_workers=8) as pool:
                    values = list(pool.map(lambda i: stores[i % 8].increment_if_below(ctx, "day", 20), range(80)))
                self.assertEqual(sorted(value for value in values if value is not None), list(range(1, 21)))
            finally:
                for store in stores:
                    store.close()
            reopened = StateStore(path)
            try:
                self.assertEqual(reopened.get(ctx, "day"), 20)
                self.assertIsNone(reopened.increment_if_below(ctx, "day", 20))
                reopened.set(ctx, "corrupt", "not-a-counter")
                with self.assertRaises(ValueError):
                    reopened.increment_if_below(ctx, "corrupt", 20)
                self.assertEqual(reopened.get(ctx, "corrupt"), "not-a-counter")
            finally:
                reopened.close()
