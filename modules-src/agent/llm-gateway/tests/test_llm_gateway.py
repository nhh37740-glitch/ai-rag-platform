import asyncio
import json
import unittest

import httpx

from core_specifications import ChatMessage, RequestContext, ToolDef
from llm_gateway import DeepSeekProvider, MockProvider


def _run(coro):
    return asyncio.run(coro)


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


class TestDeepSeekProvider(unittest.TestCase):
    def test_tool_call_roundtrip(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["auth"] = request.headers.get("authorization")
            captured["body"] = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "choices": [{
                        "message": {
                            "content": "",
                            "tool_calls": [{"id": "c1", "function": {"name": "create_issue", "arguments": '{"title":"P1"}'}}],
                        }
                    }]
                },
            )

        provider = DeepSeekProvider("k", model="deepseek-chat", transport=httpx.MockTransport(handler))
        content, calls = _run(
            provider.generate(
                RequestContext("t", "r"),
                [ChatMessage("user", "建 bug")],
                [ToolDef("create_issue", "c", {"type": "object"})],
            )
        )
        self.assertEqual(calls[0].name, "create_issue")
        self.assertEqual(calls[0].arguments, {"title": "P1"})
        self.assertEqual(captured["auth"], "Bearer k")
        self.assertEqual(captured["body"]["tools"][0]["function"]["name"], "create_issue")
        self.assertIn("/chat/completions", captured["url"])


if __name__ == "__main__":
    unittest.main()
