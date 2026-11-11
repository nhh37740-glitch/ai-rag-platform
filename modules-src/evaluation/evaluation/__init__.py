from __future__ import annotations

import math
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from core_specifications import ChatMessage
from core_specifications import RequestContext

__version__ = "0.2.0"


def _token_set(text: str) -> set:
    return set(re.findall(r"[\w一-鿿]+", text.lower()))


def _as_ranked(values: Optional[Iterable[Any]]) -> List[str]:
    """Keep retrieval order and drop duplicate identifiers."""
    seen = set()
    ranked: List[str] = []
    for value in values or []:
        key = str(value)
        if key and key not in seen:
            seen.add(key)
            ranked.append(key)
    return ranked


def ranking_metrics(
    relevant: Iterable[str],
    retrieved: Iterable[str],
    k: Optional[int] = None,
    grades: Optional[Mapping[str, float]] = None,
) -> Dict[str, float]:
    """Ranking metrics with explicit cut-off.

    ``relevant`` is the set of evidence identifiers that should be found.
    ``retrieved`` is ranked from most to least relevant. ``grades`` optionally
    maps identifiers to non-negative relevance grades for nDCG; binary
    relevance is used when it is omitted.

    Empty ``relevant`` is treated as a no-answer query: recall, precision and
    MRR are 0.0 because no evidence exists to retrieve. Callers should report
    no-answer queries separately instead of averaging them into answerable
    questions.
    """
    relevant_set = {str(item) for item in relevant}
    ranked = _as_ranked(retrieved)
    cut = len(ranked) if k is None else max(0, int(k))
    ranked = ranked[:cut]
    if not relevant_set:
        return {"k": cut, "recall_at_k": 0.0, "precision_at_k": 0.0, "mrr_at_k": 0.0, "ndcg_at_k": 0.0}

    hits = [item for item in ranked if item in relevant_set]
    recall = len(set(hits)) / len(relevant_set)
    # Precision@k divides by the requested cut-off, not by how many unique
    # results the retriever happened to return.
    precision = len(hits) / cut if cut else 0.0
    reciprocal_rank = 0.0
    for rank, item in enumerate(ranked, start=1):
        if item in relevant_set:
            reciprocal_rank = 1.0 / rank
            break

    grade_map = {str(key): float(value) for key, value in (grades or {}).items()}
    gains = [grade_map.get(item, 1.0 if item in relevant_set else 0.0) for item in ranked]
    dcg = sum((2.0 ** gain - 1.0) / math.log2(rank + 1) for rank, gain in enumerate(gains, start=1))
    ideal = sorted(
        [grade_map.get(item, 1.0) for item in relevant_set],
        reverse=True,
    )[:cut]
    idcg = sum((2.0 ** gain - 1.0) / math.log2(rank + 1) for rank, gain in enumerate(ideal, start=1))
    ndcg = dcg / idcg if idcg > 0 else 0.0
    return {
        "k": cut,
        "recall_at_k": round(recall, 4),
        "precision_at_k": round(precision, 4),
        "mrr_at_k": round(reciprocal_rank, 4),
        "ndcg_at_k": round(ndcg, 4),
    }


def evaluate_qa(ctx: RequestContext, qa_set: Dict[str, Any]) -> Dict[str, Any]:
    """Evaluate one retrieval/answer pair without inventing answer scores.

    Retrieval uses Recall@k, Precision@k, MRR@k and nDCG@k. The only answer
    signal computed locally is token overlap, and it is labelled as a
    heuristic. ``answer_relevance`` is ``None`` unless the caller supplies a
    completed LLM-judge result; a failed judge stays unavailable instead of
    falling back to answer length.
    """
    expected = [str(item) for item in qa_set.get("expected_contexts", [])]
    retrieved = _as_ranked(qa_set.get("retrieved", []))
    metrics = ranking_metrics(expected, retrieved, qa_set.get("k"), qa_set.get("grades"))

    answer = str(qa_set.get("answer", ""))
    answer_terms = _token_set(answer)
    context_terms = _token_set(
        " ".join(qa_set.get("retrieved_texts", qa_set.get("retrieved", [])))
    )
    overlap = len(answer_terms & context_terms) / len(answer_terms) if answer_terms else 0.0
    judge = qa_set.get("judge")
    judge_status = "unavailable"
    answer_relevance = None
    if isinstance(judge, dict):
        judge_status = str(judge.get("status", "unavailable"))
        if judge_status == "ok" and judge.get("score") is not None:
            answer_relevance = judge["score"]
    return {
        "question": qa_set.get("question", ""),
        "retrieval": metrics,
        "answer": {
            "faithfulness_token_overlap": round(overlap, 4),
            "faithfulness_method": "token_overlap_heuristic",
            "answer_relevance": answer_relevance,
            "judge_status": judge_status,
        },
    }


async def llm_as_judge(
    ctx: RequestContext,
    provider,
    question: str,
    answer: str,
    context: str,
) -> Dict[str, Any]:
    """Ask an LLM for a 1-10 score and return a structured status.

    The result is never fabricated. Provider failures, empty responses and
    unparseable scores return ``status='unavailable'`` with a reason. Callers
    must report that status instead of substituting a heuristic score.
    """
    prompt = (
        "作为评审，请仅输出 1-10 的整数分数，评价回答是否准确、忠实于给定资料。\n"
        f"问题: {question}\n资料: {context}\n回答: {answer}\n分数:"
    )
    try:
        score_text, _ = await provider.generate(ctx, [ChatMessage("user", prompt)], None)
    except Exception as exc:  # noqa: BLE001 - status must survive provider failures
        return {"status": "unavailable", "reason": type(exc).__name__, "score": None}
    match = re.search(r"\b(\d{1,2})\b", str(score_text or ""))
    if not match:
        return {"status": "unavailable", "reason": "unparseable_response", "score": None}
    score = int(match.group(1))
    if score < 1 or score > 10:
        return {"status": "unavailable", "reason": "score_out_of_range", "score": None}
    return {"status": "ok", "reason": "", "score": score}


def evaluate_agent(ctx: RequestContext, trajectory: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Summarise an agent trajectory: tool accuracy, task success and latency."""
    total = len(trajectory)
    if total == 0:
        return {"tool_accuracy": 0.0, "task_success": 0.0, "avg_latency_ms": 0.0}
    tool_ok = sum(1 for item in trajectory if item.get("tool_ok"))
    task_ok = sum(1 for item in trajectory if item.get("success"))
    latencies = [item.get("latency_ms", 0) for item in trajectory]
    return {
        "tool_accuracy": round(tool_ok / total, 3),
        "task_success": round(task_ok / total, 3),
        "avg_latency_ms": round(sum(latencies) / total, 1),
    }


__all__ = ["evaluate_agent", "evaluate_qa", "llm_as_judge", "ranking_metrics"]
