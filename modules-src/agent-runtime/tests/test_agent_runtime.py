import asyncio
import unittest

from agent_runtime import AgentRuntime
from core_contracts import RequestContext
from llm_gateway import MockProvider
from memory import make_memory
from observability import make_trace_store
from rag_core import InMemoryVectorStore, embed
from skill_runtime import SkillRegistry
from tool_runtime import ToolRegistry


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class TestAgentRuntime(unittest.TestCase):
    def test_qa(self):
        store = InMemoryVectorStore()
        chunks = ["API 认证需要 Bearer token", "故障 SOP：网关 keep-alive 超时"]
        store.add("api-doc", chunks, embed(chunks))
        rt = AgentRuntime(
            provider=MockProvider("qa"),
            vector_store=store,
            memory=make_memory("data/_tests/art.db"),
            tools=ToolRegistry(),
            skills=SkillRegistry(),
            tracing=make_trace_store(),
        )
        out = _run(rt.run(RequestContext("t", "r", "u", "s"), "API 如何认证？"))
        self.assertIn("Authorization", out)


if __name__ == "__main__":
    unittest.main()
