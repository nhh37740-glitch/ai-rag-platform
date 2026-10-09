import unittest

from core_specifications import RequestContext, ToolCall, ToolDef
from tool_runtime import ToolRegistry, default_registry, tool


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

    def test_context_aware_tool_receives_hidden_context(self):
        reg = ToolRegistry()
        ctx = RequestContext("trace", "request")
        runtime_context = {"knowledge_base_ids": ["kb-a"]}

        def search(query: str, *, ctx, runtime_context) -> str:
            return (
                f"{ctx.trace_id}:{ctx.request_id}:{query}:"
                f"{runtime_context['knowledge_base_ids'][0]}"
            )

        reg.register(
            ToolDef(
                "search_knowledge_base",
                "search",
                {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                },
            ),
            search,
            context_aware=True,
        )
        out = reg.execute(
            ctx,
            ToolCall(
                "1",
                "search_knowledge_base",
                {
                    "query": "奥卡姆剃刀",
                    "ctx": "untrusted",
                    "runtime_context": {"knowledge_base_ids": ["wrong"]},
                },
            ),
            runtime_context=runtime_context,
        )
        self.assertEqual(out, "trace:request:奥卡姆剃刀:kb-a")

    def test_plain_tool_does_not_receive_runtime_context(self):
        reg = ToolRegistry()

        def echo(value: str) -> str:
            return value

        reg.register(ToolDef("echo", "echo", {"type": "object"}), echo)
        out = reg.execute(
            RequestContext("t", "r"),
            ToolCall("1", "echo", {"value": "ok"}),
            runtime_context={"private": True},
        )
        self.assertEqual(out, "ok")

    def test_decorator_accepts_context_aware_option(self):
        name = "test_context_aware_decorator"

        @tool(name, "decorated", {"type": "object"}, context_aware=True)
        def decorated(value: str, *, ctx, runtime_context) -> str:
            return f"{value}:{ctx.trace_id}:{runtime_context['scope']}"

        out = default_registry().execute(
            RequestContext("trace", "request"),
            ToolCall("1", name, {"value": "ok"}),
            runtime_context={"scope": "kb"},
        )
        self.assertEqual(out, "ok:trace:kb")


if __name__ == "__main__":
    unittest.main()
