import unittest
from datetime import datetime
from unittest.mock import patch

from auth_facade import DailyQueryQuota
from core_specifications import RequestContext


class AtomicPort:
    def __init__(self):
        self.values = {}

    def get(self, ctx, key):
        return self.values.get((ctx.user_id, key))

    def increment_if_below(self, ctx, key, limit):
        count = self.get(ctx, key) or 0
        if count >= limit:
            return None
        self.values[(ctx.user_id, key)] = count + 1
        return count + 1


class DailyQuotaTests(unittest.TestCase):
    def test_beijing_midnight_rollover_and_forged_users_share_budget(self):
        port = AtomicPort()
        quota = DailyQueryQuota(port)
        with patch("auth_facade.datetime") as clock:
            clock.now.return_value = datetime.fromisoformat("2026-10-10T23:59:59+08:00")
            for i in range(20):
                result = quota.reserve(RequestContext("t", "r", "forged-" + str(i), str(i)))
            self.assertEqual(result["remaining"], 0)
            self.assertEqual(result["reset_at"], "2026-10-11T00:00:00+08:00")
            reopened = DailyQueryQuota(port)
            with self.assertRaises(PermissionError):
                reopened.reserve(RequestContext("t", "r", "new-user"))
            clock.now.return_value = datetime.fromisoformat("2026-10-11T00:00:00+08:00")
            self.assertEqual(reopened.status(RequestContext("t", "r"))["used"], 0)
            self.assertEqual(reopened.reserve(RequestContext("t", "r"))["remaining"], 19)
