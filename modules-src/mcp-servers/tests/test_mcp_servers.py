import unittest

from mcp_servers import build_default_server


class TestMcpServers(unittest.TestCase):
    def test_tools_and_call(self):
        s = build_default_server()
        self.assertGreaterEqual(len(s.tools()), 3)
        r = s.call("create_issue", {"title": "P1", "priority": "P1"})
        self.assertEqual(r["result"]["priority"], "P1")
        r2 = s.call("nope", {})
        self.assertIn("error", r2)


if __name__ == "__main__":
    unittest.main()
