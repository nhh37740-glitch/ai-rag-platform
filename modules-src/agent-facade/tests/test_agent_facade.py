import asyncio
import tempfile
import unittest
from pathlib import Path

from agent_facade import AgentService, make_provider
from core_specifications import MemoryEntry, RequestContext, ToolCall, ToolDef
from llm_gateway import DeepSeekProvider, MockProvider


RAG_NAMES = (
    "search_knowledge_base", "hybrid_search_knowledge_base",
    "keyword_search_knowledge_base", "list_knowledge_documents", "read_knowledge_document",
)


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


class FakeData:
    def __init__(self):
        self.memory = FakeMemory()
        self.close_calls = 0

    def initialize(self, ctx):
        pass

    def memory_store(self, ctx):
        return self.memory

    def vector_store(self, ctx):
        return object()

    def state_db(self, ctx):
        return object()

    def close(self, ctx):
        self.close_calls += 1


class FakeRag:
    def __init__(self):
        self.calls = []
        self.close_calls = 0

    def tool_definitions(self, ctx):
        return [ToolDef(name, "Knowledge lookup", {"type": "object"}) for name in RAG_NAMES]

    def execute_tool(self, ctx, call, knowledge_base_ids):
        self.calls.append((ctx, call, list(knowledge_base_ids)))
        return "retrieved: " + call.name

    def close(self):
        self.close_calls += 1


class FakeTracing:
    def __init__(self):
        self.events = []

    def record(self, span):
        self.events.append(span)

    def get(self, trace_id):
        return [span for span in self.events if span.trace_id == trace_id]


class ScriptedProvider:
    def __init__(self, scripted_calls=()):
        self.scripted_calls = list(scripted_calls)
        self.system_prompt = ""
        self.close_calls = 0

    async def generate(self, ctx, messages, tools=None):
        self.system_prompt = messages[0].content
        if self.scripted_calls:
            return "", [self.scripted_calls.pop(0)]
        results = [message.content for message in messages if message.role == "tool"]
        return "answer: " + (results[-1] if results else messages[-1].content), []

    async def stream(self, ctx, messages, tools=None):
        text, _ = await self.generate(ctx, messages, tools)
        yield text

    async def aclose(self):
        self.close_calls += 1


class TestAgentService(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.ctx = RequestContext("trace", "request", "user", "session")
        self.data = FakeData()
        self.rag = FakeRag()
        self.tracing = FakeTracing()

    def service(self, provider=None, **kwargs):
        return AgentService(self.data, self.rag, self.tracing, provider=provider, **kwargs)

    async def test_A01_mock_completes_turn_with_injected_ports(self):
        service = self.service()
        self.assertIsInstance(service.provider, MockProvider)
        answer = await service.run(self.ctx, "你好")
        self.assertIsInstance(answer, str)
        self.assertTrue(answer)
        self.assertEqual([message.role for message in service.history(self.ctx)], ["user", "assistant"])
        self.assertEqual(len(service.tool_definitions(self.ctx)), 5)
        self.assertTrue(self.tracing.get(self.ctx.trace_id))

    async def test_A02_all_rag_handlers_ignore_forged_scope_and_context(self):
        calls = [ToolCall(str(index), name, {
            "query": "question", "knowledge_base_ids": ["private"],
            "ctx": "forged", "runtime_context": {"knowledge_base_ids": ["private"]},
        }) for index, name in enumerate(RAG_NAMES)]
        service = self.service(ScriptedProvider(calls))
        await service.run(self.ctx, "查知识库", ["selected", "selected"])
        self.assertEqual(len(self.rag.calls), 5)
        for received_ctx, call, scope in self.rag.calls:
            self.assertIs(received_ctx, self.ctx)
            self.assertEqual(scope, ["selected"])
            self.assertEqual(call.arguments, {"query": "question"})
        self.assertEqual({span.trace_id for span in self.tracing.events}, {self.ctx.trace_id})

    async def test_A02_unselected_scope_remains_empty(self):
        provider = ScriptedProvider([ToolCall("search", RAG_NAMES[0], {"query": "q", "knowledge_base_ids": ["private"]})])
        service = self.service(provider)
        await service.run(self.ctx, "question")
        self.assertEqual(self.rag.calls[0][2], [])

    async def test_A03_extra_tool_runs_and_real_skill_body_reaches_provider(self):
        with tempfile.TemporaryDirectory() as temp:
            skill = Path(temp) / "review"
            skill.mkdir()
            (skill / "SKILL.md").write_text(
                "---\nname: review\ndescription: review\nalways: true\n---\n"
                "FULL INSTRUCTIONS: inspect ownership and list concrete evidence.\n", encoding="utf-8")
            provider = ScriptedProvider([ToolCall("custom", "double", {"value": 6})])
            service = self.service(provider, skill_dir=temp)
            observed = []

            def double(value, *, ctx, runtime_context):
                observed.append((ctx, runtime_context["user_input"]))
                return value * 2

            definition = ToolDef("double", "Double number", {"type": "object"})
            service.register_tool(self.ctx, definition, double, context_aware=True)
            definition.name = "mutated after registration"
            answer = await service.run(self.ctx, "review number")
            self.assertIn("12", answer)
            self.assertEqual(observed, [(self.ctx, "review number")])
            self.assertIn("FULL INSTRUCTIONS: inspect ownership and list concrete evidence.", provider.system_prompt)
            for name in RAG_NAMES:
                with self.assertRaises(ValueError):
                    service.register_tool(self.ctx, ToolDef(name, "override", {}), lambda: "bad")
            snapshot = service.tool_definitions(self.ctx)
            snapshot[0].parameters["modified"] = True
            self.assertNotIn("modified", service.tool_definitions(self.ctx)[0].parameters)

    async def test_A04_histories_are_copied_and_isolated_by_user_and_session(self):
        service = self.service(ScriptedProvider())
        contexts = [self.ctx, RequestContext("t2", "r2", "user", "other-session"),
                    RequestContext("t3", "r3", "other-user", "session")]
        for index, ctx in enumerate(contexts):
            await service.run(ctx, f"input-{index}")
        for index, ctx in enumerate(contexts):
            snapshot = service.history(ctx)
            self.assertEqual(snapshot[0].content, f"input-{index}")
            snapshot[0].content = "changed"
            snapshot[0].tool_calls.append(ToolCall("bad", "fake", {"nested": []}))
            snapshot.clear()
            pristine = service.history(ctx)
            self.assertEqual(pristine[0].content, f"input-{index}")
            self.assertEqual(pristine[0].tool_calls, [])
        self.assertEqual(service.history(RequestContext("t", "r", "unknown", "session")), [])

    async def test_A05_close_is_idempotent_and_does_not_close_dependencies(self):
        provider = ScriptedProvider()
        service = self.service(provider)
        await service.run(self.ctx, "first")
        await service.aclose(self.ctx)
        await service.aclose(self.ctx)
        self.assertEqual((self.data.close_calls, self.rag.close_calls, provider.close_calls), (0, 0, 0))
        self.assertIs(service.provider, provider)
        with self.assertRaises(RuntimeError):
            await service.run(self.ctx, "again")
        with self.assertRaises(RuntimeError):
            service.register_tool(self.ctx, ToolDef("x", "x", {}), lambda: None)
        with self.assertRaises(RuntimeError):
            service.history(self.ctx)
        with self.assertRaises(RuntimeError):
            service.tool_definitions(self.ctx)

    async def test_empty_input_and_insufficient_rounds_fail(self):
        service = self.service()
        for input_text in ("", " \n\t"):
            with self.assertRaises(ValueError):
                await service.run(self.ctx, input_text)
        self.assertEqual(service.history(self.ctx), [])
        with self.assertRaises(ValueError):
            self.service(max_tool_rounds=9)


class TestProviderFactory(unittest.TestCase):
    def test_empty_key_uses_mock_and_scenario(self):
        provider = make_provider(scenario="example")
        self.assertIsInstance(provider, MockProvider)
        self.assertEqual(provider.scenario, "example")

    def test_supplied_key_constructs_configured_deepseek_without_network(self):
        provider = make_provider("fake-test-key", "https://example.invalid/", "test-model")
        self.assertIsInstance(provider, DeepSeekProvider)
        self.assertEqual(provider.base_url, "https://example.invalid")
        self.assertEqual(provider.model, "test-model")


if __name__ == "__main__":
    unittest.main()
