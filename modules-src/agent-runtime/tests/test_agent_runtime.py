import asyncio
import unittest

from agent_runtime import AgentRuntime
from core_contracts import RequestContext, ToolCall, ToolDef
from memory import make_memory
from observability import make_trace_store
from skill_runtime import SkillRegistry
from tool_runtime import ToolRegistry


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class SearchThenAnswerProvider:
    def __init__(self):
        self.calls = 0
        self.system_prompt = ""

    async def generate(self, ctx, messages, tools=None):
        self.calls += 1
        self.system_prompt = messages[0].content
        if self.calls == 1:
            return "", [ToolCall("search-1", "search_knowledge_base", {"query": "奥卡姆剃刀"})]
        tool_result = next(message.content for message in reversed(messages) if message.role == "tool")
        return "已根据检索回答：" + tool_result, []


class RewriteThenAnswerProvider:
    def __init__(self):
        self.calls = 0

    async def generate(self, ctx, messages, tools=None):
        self.calls += 1
        if self.calls == 1:
            return "", [ToolCall("search-1", "search_knowledge_base", {"query": "原始查询"})]
        if self.calls == 2:
            return "", [ToolCall("search-2", "search_knowledge_base", {"query": "改写查询"})]
        return "第二次检索后回答", []


class TestAgentRuntime(unittest.TestCase):
    def test_agent_calls_context_aware_rag_tool(self):
        registry = ToolRegistry()
        observed = {}

        def search_knowledge_base(query, *, ctx, runtime_context):
            observed["query"] = query
            observed["trace_id"] = ctx.trace_id
            observed["knowledge_base_ids"] = runtime_context["knowledge_base_ids"]
            return "006-归纳偏向"

        registry.register(
            ToolDef(
                "search_knowledge_base",
                "检索当前选中的知识库",
                {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            ),
            search_knowledge_base,
            context_aware=True,
        )
        provider = SearchThenAnswerProvider()
        runtime = AgentRuntime(
            provider=provider,
            memory=make_memory("data/_tests/agent-runtime.db"),
            tools=registry,
            skills=SkillRegistry(),
            tracing=make_trace_store(),
        )

        answer = _run(
            runtime.run(
                RequestContext("trace", "request", "user", "session"),
                "奥卡姆剃刀的内容是什么？",
                ["cmrc2018-demo"],
            )
        )

        self.assertIn("006-归纳偏向", answer)
        self.assertEqual(observed["query"], "奥卡姆剃刀")
        self.assertEqual(observed["trace_id"], "trace")
        self.assertEqual(observed["knowledge_base_ids"], ["cmrc2018-demo"])
        self.assertIn("已选择: cmrc2018-demo", provider.system_prompt)
        self.assertIn("即使你确信自己知道答案，也必须先检索核实", provider.system_prompt)

    def test_tool_round_limit_cannot_be_below_ten(self):
        with self.assertRaisesRegex(ValueError, "10"):
            AgentRuntime(
                provider=SearchThenAnswerProvider(),
                memory=make_memory("data/_tests/agent-runtime-limit.db"),
                tools=ToolRegistry(),
                skills=SkillRegistry(),
                tracing=make_trace_store(),
                max_tool_rounds=9,
            )

    def test_agent_can_rewrite_and_search_again(self):
        registry = ToolRegistry()
        queries = []

        def search_knowledge_base(query, *, ctx, runtime_context):
            queries.append(query)
            return "无关结果" if len(queries) == 1 else "直接证据"

        registry.register(
            ToolDef("search_knowledge_base", "检索", {"type": "object"}),
            search_knowledge_base,
            context_aware=True,
        )
        provider = RewriteThenAnswerProvider()
        runtime = AgentRuntime(
            provider=provider,
            memory=make_memory("data/_tests/agent-runtime-rewrite.db"),
            tools=registry,
            skills=SkillRegistry(),
            tracing=make_trace_store(),
        )

        answer = _run(
            runtime.run(
                RequestContext("trace-rewrite", "request", "user", "session-rewrite"),
                "请从知识库回答",
                ["cmrc2018-demo"],
            )
        )

        self.assertEqual(answer, "第二次检索后回答")
        self.assertEqual(queries, ["原始查询", "改写查询"])
        self.assertEqual(provider.calls, 3)


if __name__ == "__main__":
    unittest.main()
