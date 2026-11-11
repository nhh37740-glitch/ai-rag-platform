import unittest

import httpx

from mcp_servers.github import build_github_server
from mcp_servers import build_default_server


class TestMcpServers(unittest.TestCase):
    def test_tools_and_call(self):
        s = build_default_server()
        self.assertGreaterEqual(len(s.tools()), 3)
        r = s.call("create_issue", {"title": "P1", "priority": "P1"})
        self.assertEqual(r["result"]["priority"], "P1")
        r2 = s.call("nope", {})
        self.assertIn("error", r2)

    def test_github_connector(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=[{"sha": "abc123", "commit": {"message": "fix: keep-alive"}}])

        client = httpx.Client(transport=httpx.MockTransport(handler))
        s = build_github_server(repo="x/y", client=client)
        r = s.call("get_commits", {"per_page": 5})
        self.assertEqual(r["result"][0]["message"], "fix: keep-alive")


if __name__ == "__main__":
    unittest.main()
