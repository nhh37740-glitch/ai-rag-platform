import asyncio
import unittest

from mcp_gateway import MockClient, normalize_to_tool


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class TestMcpGateway(unittest.TestCase):
    def test_normalize(self):
        t = normalize_to_tool({"function": {"name": "x", "description": "d", "parameters": {"type": "object"}}})
        self.assertEqual(t.name, "x")
        self.assertEqual(t.description, "d")

    def test_mock_client(self):
        c = MockClient()
        tools = _run(c.list_tools())
        self.assertGreaterEqual(len(tools), 1)
        out = _run(c.call_tool("create_issue", {"title": "P1", "priority": "P1"}))
        self.assertIn("P1", out)


if __name__ == "__main__":
    unittest.main()
