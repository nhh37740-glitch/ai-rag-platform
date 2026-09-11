import json
import unittest
from unittest.mock import patch

from core_contracts import Citation, RequestContext, RetrievalResult
from rag_skill import MAX_TOP_K, RagSkill


class RecordingTraceStore:
    def __init__(self):
        self.events = []

    def record(self, span):
        self.events.append(span)


class TestRagSkill(unittest.TestCase):
    def setUp(self):
        self.store = object()
        self.tracing = RecordingTraceStore()
        self.skill = RagSkill(self.store, self.tracing)
        self.ctx = RequestContext("trace-1", "request-1")

    def test_tool_definition_does_not_expose_scope(self):
        definition = self.skill.tool_definition()

        self.assertEqual(definition.name, "search_knowledge_base")
        self.assertEqual(definition.parameters["required"], ["query"])
        self.assertIn("top_k", definition.parameters["properties"])
        self.assertNotIn("knowledge_base_ids", definition.parameters["properties"])

    @patch("rag_skill.retrieve")
    def test_execute_uses_only_injected_scope_and_returns_json(self, mocked_retrieve):
        mocked_retrieve.return_value = RetrievalResult(
            query="奥卡姆剃刀",
            contexts=["最简单而又一致的假设是最佳的。"],
            citations=[
                Citation(
                    source_id="cmrc2018-demo/006-归纳偏向",
                    title="006-归纳偏向",
                    text="最简单而又一致的假设是最佳的。",
                    score=0.91,
                    metadata={"knowledge_base_id": "cmrc2018-demo"},
                )
            ],
        )

        payload = json.loads(
            self.skill.execute(
                self.ctx,
                "奥卡姆剃刀",
                ["cmrc2018-demo", "cmrc2018-demo"],
                top_k=3,
            )
        )

        mocked_retrieve.assert_called_once_with(
            self.ctx,
            "奥卡姆剃刀",
            self.store,
            scope=["cmrc2018-demo"],
            top_k=3,
        )
        self.assertEqual(payload["hit_count"], 1)
        self.assertEqual(payload["citations"][0]["title"], "006-归纳偏向")
        self.assertEqual(self.tracing.events[0].span, "rag")
        self.assertEqual(self.tracing.events[0].status, "ok")
        self.assertEqual(self.tracing.events[0].meta["hits"][0]["rank"], 1)

    def test_invalid_top_k_is_traced_as_an_error(self):
        with self.assertRaises(ValueError):
            self.skill.execute(self.ctx, "问题", ["kb"], top_k=MAX_TOP_K + 1)

        self.assertEqual(len(self.tracing.events), 1)
        self.assertEqual(self.tracing.events[0].status, "error")
        self.assertEqual(self.tracing.events[0].meta["knowledge_base_ids"], ["kb"])


if __name__ == "__main__":
    unittest.main()
