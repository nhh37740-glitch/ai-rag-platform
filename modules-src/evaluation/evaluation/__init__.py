from __future__ import annotations

from typing import Any, Dict, List

from core_contracts import ChatMessage
from core_contracts import RequestContext

__version__ = "0.1.0"


def _token_set(text: str) -> set:
    import re

    return set(re.findall(r"[\w\u4e00-\u9fff]+", text.lower()))


def evaluate_qa(ctx: RequestContext, qa: Dict[str, Any]) -> Dict[str, Any]:
    """对单个问答对做 RAG 指标评估（近似规则，后续可接 DeepEval/LLM-as-Judge）。"""
    expected = set(qa.get("expected_contexts", []))
    retrieved = set(qa.get("retrieved", []))
    recall = len(expected & retrieved) / len(expected) if expected else 0.0
    precision = len(expected & retrieved) / len(retrieved) if retrieved else 0.0

    answer = qa.get("answer", "")
    answer_terms = _token_set(answer)
    context_terms = _token_set(" ".join(qa.get("retrieved_texts", qa.get("retrieved", []))))
    faithfulness = len(answer_terms & context_terms) / len(answer_terms) if answer_terms else 0.0
    relevance = round(min(1.0, len(answer) / max(20, len(qa.get("question", "")))), 3)
    return {
        "question": qa.get("question", ""),
        "recall": round(recall, 3),
        "precision": round(precision, 3),
        "faithfulness": round(faithfulness, 3),
        "answer_relevance": relevance,
    }


async def llm_as_judge(ctx: RequestContext, provider, question: str, answer: str, context: str) -> int:
    """LLM-as-Judge：用 provider 给 1-10 分。Mock 返回启发式分数，真实 provider 接入后可换。"""
    prompt = (
        "作为评审，请仅输出 1-10 的整数分数，评价回答是否准确、忠实于给定资料的。\n"
        f"问题: {question}\n资料: {context}\n回答: {answer}\n分数:"
    )
    try:
        score_text, _ = await provider.generate(ctx, [ChatMessage("user", prompt)], None)
        import re

        m = re.search(r"\d+", score_text)
        return min(10, max(1, int(m.group()) if m else 5))
    except Exception:
        return min(10, max(1, int(len(answer) / 6)))


def evaluate_agent(ctx: RequestContext, trajectory: List[Dict[str, Any]]) -> Dict[str, Any]:
    """统计 Agent 轨迹：工具/技能选择正确率、任务成功率、平均延迟。"""
    total = len(trajectory)
    if total == 0:
        return {"tool_accuracy": 0.0, "task_success": 0.0, "avg_latency_ms": 0.0}
    tool_ok = sum(1 for t in trajectory if t.get("tool_ok"))
    task_ok = sum(1 for t in trajectory if t.get("success"))
    lats = [t.get("latency_ms", 0) for t in trajectory]
    return {
        "tool_accuracy": round(tool_ok / total, 3),
        "task_success": round(task_ok / total, 3),
        "avg_latency_ms": round(sum(lats) / total, 1),
    }


__all__ = ["evaluate_qa", "llm_as_judge", "evaluate_agent"]
