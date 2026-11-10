import asyncio
import unittest

from core_specifications import RequestContext
from evaluation import evaluate_agent, evaluate_qa, llm_as_judge, ranking_metrics


class FailingProvider:
    async def generate(self, ctx, messages, tools=None):
        raise RuntimeError("upstream unavailable")


class UnparseableProvider:
    async def generate(self, ctx, messages, tools=None):
        return "没有分数", []


class ScoreProvider:
    async def generate(self, ctx, messages, tools=None):
        return "8", []


class TestRankingMetrics(unittest.TestCase):
    def test_perfect_ranking(self):
        r = ranking_metrics(["a", "b"], ["a", "b", "c"], k=3)
        self.assertEqual(r["recall_at_k"], 1.0)
        self.assertEqual(r["precision_at_k"], 0.6667)
        self.assertEqual(r["mrr_at_k"], 1.0)
        self.assertEqual(r["ndcg_at_k"], 1.0)

    def test_miss_and_order(self):
        r = ranking_metrics(["a", "b"], ["x", "a", "y"], k=3)
        self.assertEqual(r["recall_at_k"], 0.5)
        self.assertEqual(r["precision_at_k"], 0.3333)
        self.assertEqual(r["mrr_at_k"], 0.5)
        self.assertLess(r["ndcg_at_k"], 0.7)

    def test_cutoff(self):
        r = ranking_metrics(["a"], ["x", "y", "a"], k=2)
        self.assertEqual(r["recall_at_k"], 0.0)
        self.assertEqual(r["mrr_at_k"], 0.0)

    def test_graded_ndcg(self):
        r = ranking_metrics(["a", "b"], ["a", "b"], k=2, grades={"a": 2, "b": 1})
        self.assertEqual(r["ndcg_at_k"], 1.0)

    def test_no_answer_query_is_not_averaged(self):
        r = ranking_metrics([], ["a"], k=1)
        self.assertEqual(r["recall_at_k"], 0.0)
        self.assertEqual(r["ndcg_at_k"], 0.0)


class TestEvaluation(unittest.TestCase):
    def test_qa_metrics_are_structured(self):
        r = evaluate_qa(RequestContext("t", "r"), {
            "question": "XX API 如何认证？",
            "expected_contexts": ["api_docs"],
            "retrieved": ["api_docs", "sop"],
            "answer": "在请求头带 Authorization Bearer token 即可认证",
        })
        self.assertEqual(r["retrieval"]["recall_at_k"], 1.0)
        self.assertLessEqual(r["retrieval"]["precision_at_k"], 1.0)
        self.assertEqual(r["answer"]["faithfulness_method"], "token_overlap_heuristic")
        self.assertIsNone(r["answer"]["answer_relevance"])
        self.assertEqual(r["answer"]["judge_status"], "unavailable")

    def test_judge_ok(self):
        s = asyncio.run(llm_as_judge(RequestContext("t", "r"), ScoreProvider(), "q", "答案", "资料"))
        self.assertEqual(s["status"], "ok")
        self.assertEqual(s["score"], 8)

    def test_judge_failure_is_unavailable_not_length_score(self):
        s = asyncio.run(llm_as_judge(RequestContext("t", "r"), FailingProvider(), "q", "很长" * 50, "资料"))
        self.assertEqual(s["status"], "unavailable")
        self.assertEqual(s["reason"], "RuntimeError")
        self.assertIsNone(s["score"])

    def test_unparseable_judge_is_unavailable(self):
        s = asyncio.run(llm_as_judge(RequestContext("t", "r"), UnparseableProvider(), "q", "答案", "资料"))
        self.assertEqual(s["status"], "unavailable")
        self.assertEqual(s["reason"], "unparseable_response")

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
