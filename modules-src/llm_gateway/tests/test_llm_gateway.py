import asyncio
import unittest

from core_contracts import ChatMessage, RequestContext, ToolDef
from llm_gateway import MockProvider


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class TestMockProvider(unittest.TestCase):
    def test_answer(self):
        p = MockProvider("qa")
        out = _run(p.generate(RequestContext("t", "r"), [ChatMessage("user", "API 如何认证？")], []))
        self.assertIn("Authorization", out[0])

    def test_tool_call(self):
        p = MockProvider()
        tools = [ToolDef("create_issue", "create", {"type": "object"})]
        out = _run(p.generate(RequestContext("t", "r"), [ChatMessage("user", "帮我建一个 Bug")], tools))
        self.assertEqual(out[1][0].name, "create_issue")


if __name__ == "__main__":
    unittest.main()
