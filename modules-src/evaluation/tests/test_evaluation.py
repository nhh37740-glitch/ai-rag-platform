import unittest
import asyncio

from core_specifications import RequestContext
from evaluation import evaluate_agent, evaluate_qa, llm_as_judge
from llm_gateway import MockProvider


class TestEvaluation(unittest.TestCase):
    def test_qa_metrics(self):
        r = evaluate_qa(RequestContext("t", "r"), {
            "question": "XX API 如何认证？",
            "expected_contexts": ["api_docs"],
            "retrieved": ["api_docs", "sop"],
            "answer": "在请求头带 Authorization Bearer token 即可认证",
        })
        self.assertGreaterEqual(r["recall"], 0.99)
        self.assertLessEqual(r["precision"], 0.99)

    def test_judge(self):
        s = asyncio.run(llm_as_judge(RequestContext("t", "r"), MockProvider("qa"), "q", "很长的答案内容", "资料"))
        self.assertGreaterEqual(s, 1)

    def test_agent(self):
        r = evaluate_agent(RequestContext("t", "r"), [
            {"tool_ok": True, "success": True, "latency_ms": 10},
            {"tool_ok": False, "success": False, "latency_ms": 30},
        ])
        self.assertEqual(r["tool_accuracy"], 0.5)
        self.assertEqual(r["task_success"], 0.5)
        self.assertEqual(r["avg_latency_ms"], 20.0)


if __name__ == "__main__":
    unittest.main()
