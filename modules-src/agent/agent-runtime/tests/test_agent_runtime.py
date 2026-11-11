import asyncio
import json
import unittest

from agent_runtime import (
    DUPLICATE_RETRIEVAL_MESSAGE,
    MAX_RETRIEVAL_REMINDERS,
    NO_EVIDENCE_ANSWER,
    RETRIEVAL_TOOL_NAMES,
    SKIPPED_RETRIEVAL_MESSAGE,
    AgentRuntime,
)
from core_specifications import MemoryEntry, RequestContext, ToolCall, ToolDef
from observability import make_trace_store
from skill_runtime import SkillRegistry
from tool_runtime import ToolRegistry


def _run(coro):
    return asyncio.run(coro)


class FakeMemory:
    def __init__(self):
        self.entries = {}

    def get(self, ctx, namespace, key):
        return self.entries.get((ctx.user_id, ctx.session_id, namespace, key))

    def write(self, ctx, namespace, key, content, importance=0.0):
        entry = MemoryEntry(key, namespace, key, content, "test", importance)
        self.entries[(ctx.user_id, ctx.session_id, namespace, key)] = entry
        return entry

    def search(self, ctx, namespace, query, top_k=5):
        return [entry for key, entry in self.entries.items()
                if key[:3] == (ctx.user_id, ctx.session_id, namespace)][:top_k]

    def forget(self, ctx, namespace, key):
        self.entries.pop((ctx.user_id, ctx.session_id, namespace, key), None)


def make_memory(_path):
    """Protocol fake: runtime tests create no persistent database files."""
    return FakeMemory()


def _recorder(name, executed):
    def handler(query=None, source_id=None, filename=None, content=None, *, ctx, runtime_context):
        executed.append(name)
        return f"结果:{name}"

    return handler


def _register_all(registry, executed):
    for name in sorted(RETRIEVAL_TOOL_NAMES):
        registry.register(
            ToolDef(name, "知识库检索工具", {"type": "object", "properties": {}}),
            _recorder(name, executed),
            context_aware=True,
        )


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
    def test_history_returns_deep_copied_user_session_snapshot(self):
        runtime = AgentRuntime(
            provider=NeverRetrievesProvider(), memory=FakeMemory(),
            tools=ToolRegistry(), skills=SkillRegistry(), tracing=make_trace_store(),
        )
        ctx = RequestContext("trace", "request", "user", "session")
        _run(runtime.run(ctx, "first"))
        runtime._histories[(ctx.user_id, ctx.session_id)][0].tool_calls = [
            ToolCall("id", "tool", {"nested": ["original"]})
        ]
        copied = runtime.history(ctx)
        copied[0].content = "modified"
        copied[0].tool_calls[0].arguments["nested"].append("modified")
        self.assertEqual(runtime.history(ctx)[0].content, "first")
        self.assertEqual(runtime.history(ctx)[0].tool_calls[0].arguments, {"nested": ["original"]})
        self.assertEqual(runtime.history(RequestContext("t", "r", "user", "other")), [])
        self.assertEqual(runtime.history(RequestContext("t", "r", "other", "session")), [])

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
        self.assertIn("你确信自己知道答案的问题，一律先检索再作答", provider.system_prompt)

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


class TwoRetrievalsInOneTurnProvider:
    """第一条 assistant 消息同时发出两个检索调用。"""

    def __init__(self):
        self.calls = 0
        self.messages = []

    async def generate(self, ctx, messages, tools=None):
        self.calls += 1
        if self.calls == 1:
            return "", [
                ToolCall("search-1", "search_knowledge_base", {"query": "奥卡姆剃刀"}),
                ToolCall("search-2", "hybrid_search_knowledge_base", {"query": "归纳偏向"}),
            ]
        self.messages = list(messages)
        tool_messages = [message for message in messages if message.role == "tool"]
        return "|".join(message.content for message in tool_messages), []


class RetrievalPlusFileProvider:
    """一条消息里同时有检索调用和非检索调用。"""

    def __init__(self):
        self.calls = 0

    async def generate(self, ctx, messages, tools=None):
        self.calls += 1
        if self.calls == 1:
            return "", [
                ToolCall("retrieval-1", "keyword_search_knowledge_base", {"query": "术语"}),
                ToolCall("file-1", "create_file", {"filename": "note.md", "content": "内容"}),
            ]
        tool_messages = [message for message in messages if message.role == "tool"]
        return "|".join(message.content for message in tool_messages), []


class EmptyThenClaimsProvider:
    """检索返回 0 命中后，仍尝试用引用标注收尾。"""

    def __init__(self):
        self.calls = 0

    async def generate(self, ctx, messages, tools=None):
        self.calls += 1
        if self.calls == 1:
            return "", [ToolCall("search-empty", "search_knowledge_base", {"query": "不存在的术语"})]
        return "根据检索结果 [1]，答案是龙肉。", []


class ListEmptyThenClaimsProvider:
    """文档清单为空后，仍尝试用引用标注收尾。"""

    def __init__(self):
        self.calls = 0

    async def generate(self, ctx, messages, tools=None):
        self.calls += 1
        if self.calls == 1:
            return "", [ToolCall("list-empty", "list_knowledge_documents", {})]
        return "根据资料 [1]，答案是龙肉。", []


class ZeroThenToolErrorProvider:
    """零命中后又触发一个已知工具失败，再尝试用引用标注收尾。"""

    def __init__(self):
        self.calls = 0

    async def generate(self, ctx, messages, tools=None):
        self.calls += 1
        if self.calls == 1:
            return "", [ToolCall("search-empty", "search_knowledge_base", {"query": "不存在的术语"})]
        if self.calls == 2:
            return "", [ToolCall("read-error", "read_knowledge_document", {"source_id": "missing"})]
        return "根据资料 [1]，答案是龙肉。", []


class RepeatQueryProvider:
    """连续两轮提交完全相同的检索参数。"""

    def __init__(self):
        self.calls = 0
        self.tool_messages = []

    async def generate(self, ctx, messages, tools=None):
        self.calls += 1
        if self.calls <= 2:
            return "", [ToolCall(f"search-{self.calls}", "search_knowledge_base", {"query": "重复查询"})]
        self.tool_messages = [message.content for message in messages if message.role == "tool"]
        return "已根据检索回答", []


class NeverRetrievesProvider:
    """永远不调用工具，每轮都想直接收尾。"""

    def __init__(self):
        self.calls = 0

    async def generate(self, ctx, messages, tools=None):
        self.calls += 1
        return f"第 {self.calls} 次直接回答", []


class RetrievesOnlyAfterReminderProvider:
    """第一次想直接回答，被 retrieval_guard 打回后才去检索。"""

    def __init__(self):
        self.calls = 0

    async def generate(self, ctx, messages, tools=None):
        self.calls += 1
        if self.calls == 1:
            return "我想不检索直接回答", []
        tool_messages = [message for message in messages if message.role == "tool"]
        if not tool_messages:
            return "", [ToolCall("search-1", "search_knowledge_base", {"query": "龙肉怎么吃"})]
        return "已依据检索作答：" + tool_messages[-1].content, []


class TestRetrievalRouting(unittest.TestCase):
    def test_system_prompt_describes_all_tools_and_the_one_retrieval_rule(self):
        provider = SearchThenAnswerProvider()
        runtime = AgentRuntime(
            provider=provider,
            memory=make_memory(":memory:"),
            tools=ToolRegistry(),
            skills=SkillRegistry(),
            tracing=make_trace_store(),
        )
        _run(
            runtime.run(
                RequestContext("trace", "request", "user", "session"),
                "闲聊一句",
                ["cmrc2018-demo"],
            )
        )

        for name in RETRIEVAL_TOOL_NAMES:
            self.assertIn(name, provider.system_prompt)
        self.assertIn("每轮只调用一次知识库检索工具", provider.system_prompt)
        self.assertIn("每一个问题都必须至少调用一次", provider.system_prompt)
        self.assertIn("不得在没有检索的情况下断言知识库", provider.system_prompt)

    def test_direct_answer_without_retrieval_is_sent_back(self):
        registry = ToolRegistry()
        executed = []
        _register_all(registry, executed)
        provider = RetrievesOnlyAfterReminderProvider()
        tracing = make_trace_store()
        runtime = AgentRuntime(
            provider=provider,
            memory=make_memory(":memory:"),
            tools=registry,
            skills=SkillRegistry(),
            tracing=tracing,
        )

        answer = _run(
            runtime.run(
                RequestContext("trace-guard", "request", "user", "session"),
                "龙肉怎么吃",
                ["cmrc2018-demo"],
            )
        )

        self.assertEqual(executed, ["search_knowledge_base"])
        self.assertIn("结果:search_knowledge_base", answer)
        guards = [event for event in tracing.get("trace-guard") if event.span == "retrieval_guard"]
        self.assertEqual(len(guards), 1)
        self.assertEqual(guards[0].meta["attempt"], 1)
        self.assertEqual(guards[0].meta["knowledge_base_ids"], ["cmrc2018-demo"])

    def test_reminders_are_bounded_and_never_loop_forever(self):
        provider = NeverRetrievesProvider()
        tracing = make_trace_store()
        runtime = AgentRuntime(
            provider=provider,
            memory=make_memory(":memory:"),
            tools=ToolRegistry(),
            skills=SkillRegistry(),
            tracing=tracing,
        )

        answer = _run(
            runtime.run(
                RequestContext("trace-bounded", "request", "user", "session"),
                "闲聊一句",
                ["cmrc2018-demo"],
            )
        )

        self.assertEqual(provider.calls, 1 + MAX_RETRIEVAL_REMINDERS)
        guards = [
            event for event in tracing.get("trace-bounded") if event.span == "retrieval_guard"
        ]
        self.assertEqual(len(guards), MAX_RETRIEVAL_REMINDERS)
        self.assertEqual(answer, NO_EVIDENCE_ANSWER)

    def test_no_knowledge_base_means_no_retrieval_requirement(self):
        provider = NeverRetrievesProvider()
        tracing = make_trace_store()
        runtime = AgentRuntime(
            provider=provider,
            memory=make_memory(":memory:"),
            tools=ToolRegistry(),
            skills=SkillRegistry(),
            tracing=tracing,
        )

        answer = _run(
            runtime.run(
                RequestContext("trace-no-kb", "request", "user", "session"),
                "你好",
                None,
            )
        )

        self.assertEqual(provider.calls, 1)
        self.assertEqual(
            [event for event in tracing.get("trace-no-kb") if event.span == "retrieval_guard"],
            [],
        )
        self.assertIn("直接回答", answer)

    def test_only_the_first_retrieval_call_in_a_turn_is_executed(self):
        registry = ToolRegistry()
        executed = []
        _register_all(registry, executed)
        provider = TwoRetrievalsInOneTurnProvider()

        runtime = AgentRuntime(
            provider=provider,
            memory=make_memory(":memory:"),
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

        self.assertEqual(executed, ["search_knowledge_base"])
        self.assertIn("结果:search_knowledge_base", answer)
        self.assertIn(SKIPPED_RETRIEVAL_MESSAGE, answer)
        self.assertNotIn("结果:hybrid_search_knowledge_base", answer)

    def test_skipped_call_keeps_its_tool_call_id(self):
        registry = ToolRegistry()
        executed = []
        _register_all(registry, executed)
        provider = TwoRetrievalsInOneTurnProvider()

        runtime = AgentRuntime(
            provider=provider,
            memory=make_memory(":memory:"),
            tools=registry,
            skills=SkillRegistry(),
            tracing=make_trace_store(),
        )
        _run(
            runtime.run(
                RequestContext("trace", "request", "user", "session"),
                "奥卡姆剃刀的内容是什么？",
                ["cmrc2018-demo"],
            )
        )

        tool_messages = {
            message.tool_call_id: message
            for message in provider.messages
            if message.role == "tool"
        }
        self.assertEqual(sorted(tool_messages), ["search-1", "search-2"])
        self.assertEqual(tool_messages["search-1"].content, "结果:search_knowledge_base")
        self.assertEqual(tool_messages["search-2"].content, SKIPPED_RETRIEVAL_MESSAGE)
        self.assertEqual(tool_messages["search-2"].name, "hybrid_search_knowledge_base")

    def test_non_retrieval_tool_still_runs_in_the_same_turn(self):
        registry = ToolRegistry()
        executed = []
        _register_all(registry, executed)

        def create_file(filename, content):
            executed.append("create_file")
            return f"已创建 {filename}"

        registry.register(
            ToolDef(
                "create_file",
                "创建文件",
                {
                    "type": "object",
                    "properties": {"filename": {"type": "string"}, "content": {"type": "string"}},
                },
            ),
            create_file,
        )
        provider = RetrievalPlusFileProvider()

        runtime = AgentRuntime(
            provider=provider,
            memory=make_memory(":memory:"),
            tools=registry,
            skills=SkillRegistry(),
            tracing=make_trace_store(),
        )
        answer = _run(
            runtime.run(
                RequestContext("trace", "request", "user", "session"),
                "查一下并记录",
                ["cmrc2018-demo"],
            )
        )

        self.assertEqual(executed, ["keyword_search_knowledge_base", "create_file"])
        self.assertIn("结果:keyword_search_knowledge_base", answer)
        self.assertIn("已创建 note.md", answer)

    def test_single_retrieval_call_per_turn_is_unaffected(self):
        registry = ToolRegistry()
        executed = []
        _register_all(registry, executed)

        runtime = AgentRuntime(
            provider=SearchThenAnswerProvider(),
            memory=make_memory(":memory:"),
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

        self.assertEqual(executed, ["search_knowledge_base"])
        self.assertIn("结果:search_knowledge_base", answer)
        self.assertNotIn(SKIPPED_RETRIEVAL_MESSAGE, answer)

    def test_empty_retrieval_blocks_ungrounded_answer(self):
        registry = ToolRegistry()
        registry.register(
            ToolDef("search_knowledge_base", "检索", {"type": "object"}),
            lambda query, *, ctx, runtime_context: json.dumps(
                {"tool": "search_knowledge_base", "query": query, "hit_count": 0, "citations": []},
                ensure_ascii=False,
            ),
            context_aware=True,
        )
        tracing = make_trace_store()
        runtime = AgentRuntime(
            provider=EmptyThenClaimsProvider(),
            memory=make_memory(":memory:"),
            tools=registry,
            skills=SkillRegistry(),
            tracing=tracing,
        )
        answer = _run(
            runtime.run(
                RequestContext("trace-empty", "request", "user", "session"),
                "查一个不存在的术语",
                ["cmrc2018-demo"],
            )
        )
        self.assertEqual(answer, NO_EVIDENCE_ANSWER)
        stops = [event for event in tracing.get("trace-empty") if event.span == "agent_stop"]
        self.assertEqual(stops[-1].meta["stop_reason"], "no_evidence")

    def test_empty_document_listing_does_not_count_as_evidence(self):
        registry = ToolRegistry()
        registry.register(
            ToolDef("list_knowledge_documents", "列目录", {"type": "object"}),
            lambda *, ctx, runtime_context: json.dumps(
                {"tool": "list_knowledge_documents", "document_count": 0, "documents": []},
                ensure_ascii=False,
            ),
            context_aware=True,
        )
        tracing = make_trace_store()
        runtime = AgentRuntime(
            provider=ListEmptyThenClaimsProvider(),
            memory=make_memory(":memory:"),
            tools=registry,
            skills=SkillRegistry(),
            tracing=tracing,
        )
        answer = _run(
            runtime.run(
                RequestContext("trace-list-empty", "request", "user", "session"),
                "知识库里有什么？",
                ["cmrc2018-demo"],
            )
        )
        self.assertEqual(answer, NO_EVIDENCE_ANSWER)
        stops = [event for event in tracing.get("trace-list-empty") if event.span == "agent_stop"]
        self.assertEqual(stops[-1].meta["stop_reason"], "no_evidence")

    def test_tool_error_does_not_bypass_no_evidence_guard(self):
        registry = ToolRegistry()
        registry.register(
            ToolDef("search_knowledge_base", "检索", {"type": "object"}),
            lambda query, *, ctx, runtime_context: json.dumps(
                {"tool": "search_knowledge_base", "query": query, "hit_count": 0, "citations": []},
                ensure_ascii=False,
            ),
            context_aware=True,
        )

        def broken_read(source_id, *, ctx, runtime_context):
            raise ValueError("document not found")

        registry.register(
            ToolDef("read_knowledge_document", "读文档", {"type": "object"}),
            broken_read,
            context_aware=True,
        )
        tracing = make_trace_store()
        runtime = AgentRuntime(
            provider=ZeroThenToolErrorProvider(),
            memory=make_memory(":memory:"),
            tools=registry,
            skills=SkillRegistry(),
            tracing=tracing,
        )
        answer = _run(
            runtime.run(
                RequestContext("trace-tool-error", "request", "user", "session"),
                "查一个不存在的术语",
                ["cmrc2018-demo"],
            )
        )
        self.assertEqual(answer, NO_EVIDENCE_ANSWER)
        stops = [event for event in tracing.get("trace-tool-error") if event.span == "agent_stop"]
        self.assertEqual(stops[-1].meta["stop_reason"], "no_evidence")

    def test_duplicate_retrieval_query_is_skipped(self):
        registry = ToolRegistry()
        registry.register(
            ToolDef("search_knowledge_base", "检索", {"type": "object"}),
            lambda query, *, ctx, runtime_context: json.dumps(
                {"tool": "search_knowledge_base", "query": query, "hit_count": 1, "citations": [{"text": "证据"}]},
                ensure_ascii=False,
            ),
            context_aware=True,
        )
        provider = RepeatQueryProvider()
        tracing = make_trace_store()
        runtime = AgentRuntime(
            provider=provider,
            memory=make_memory(":memory:"),
            tools=registry,
            skills=SkillRegistry(),
            tracing=tracing,
        )
        answer = _run(
            runtime.run(
                RequestContext("trace-dup", "request", "user", "session"),
                "重复查询",
                ["cmrc2018-demo"],
            )
        )
        self.assertEqual(answer, "已根据检索回答")
        self.assertEqual(provider.tool_messages.count(DUPLICATE_RETRIEVAL_MESSAGE), 1)
        guards = [event for event in tracing.get("trace-dup") if event.span == "retrieval_guard"]
        self.assertTrue(any(event.meta.get("reason") == "duplicate_query" for event in guards))


if __name__ == "__main__":
    unittest.main()
