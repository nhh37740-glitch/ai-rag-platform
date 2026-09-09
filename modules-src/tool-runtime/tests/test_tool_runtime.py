import unittest

from core_contracts import RequestContext, ToolCall, ToolDef
from tool_runtime import ToolRegistry


class TestToolRuntime(unittest.TestCase):
    def test_register_execute(self):
        reg = ToolRegistry()

        def create_issue(title: str) -> str:
            return f"issue:{title}"

        reg.register(ToolDef("create_issue", "create", {"type": "object"}), create_issue)
        ctx = RequestContext("t", "r")
        out = reg.execute(ctx, ToolCall("1", "create_issue", {"title": "P1"}))
        self.assertEqual(out, "issue:P1")

    def test_unknown_tool(self):
        reg = ToolRegistry()
        out = reg.execute(RequestContext("t", "r"), ToolCall("1", "nope", {}))
        self.assertTrue(out.startswith("ERROR"))


if __name__ == "__main__":
    unittest.main()
