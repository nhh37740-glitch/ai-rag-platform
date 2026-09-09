from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "apps", "agent-server"))

from app import runtime, vector_store  # noqa: E402
from core_contracts import RequestContext  # noqa: E402
from evaluation import evaluate_agent, evaluate_qa, llm_as_judge  # noqa: E402
from rag_core import retrieve  # noqa: E402

QA = [
    {"question": "XX API 如何认证？", "expected": ["api_docs"]},
    {"question": "连接超时怎么排查？", "expected": ["sop"]},
    {"question": "系统是怎么分层的（记忆、工具、技能）？", "expected": ["architecture"]},
]


async def main() -> None:
    report = {"qa": [], "trajectory": []}
    for qa in QA:
        ctx = RequestContext(trace_id=uuid.uuid4().hex, request_id=uuid.uuid4().hex, user_id="u", session_id="s1")
        result = retrieve(ctx, qa["question"], vector_store, top_k=3)
        answer = await runtime.run(ctx, qa["question"])
        qin = {
            "question": qa["question"],
            "expected_contexts": qa["expected"],
            "retrieved": [c.source_id for c in result.citations],
            "retrieved_texts": result.contexts,
            "answer": answer,
        }
        metrics = evaluate_qa(ctx, qin)
        judge = await llm_as_judge(ctx, runtime.provider, qa["question"], answer, " ".join(result.contexts))
        metrics["llm_judge"] = judge
        report["qa"].append(metrics)
    agent = evaluate_agent(RequestContext("t", "r"), [{"tool_ok": True, "success": True, "latency_ms": 30}])
    report["trajectory"].append(agent)
    report["summary"] = {
        "avg_recall": round(sum(m["recall"] for m in report["qa"]) / len(report["qa"]), 3),
        "avg_faithfulness": round(sum(m["faithfulness"] for m in report["qa"]) / len(report["qa"]), 3),
        "avg_answer_relevance": round(sum(m["answer_relevance"] for m in report["qa"]) / len(report["qa"]), 3),
        "avg_llm_judge": round(sum(m["llm_judge"] for m in report["qa"]) / len(report["qa"]), 2),
    }
    root = Path(__file__).resolve().parent.parent
    reports = root / "reports"
    reports.mkdir(exist_ok=True)
    (reports / "eval.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md = ["# 评测基线", "", "| 问题 | Recall | Precision | Faithfulness | AnswerRel | Judge |", "|---|---|---|---|---|---|"]
    for m in report["qa"]:
        md.append(f"| {m['question']} | {m['recall']} | {m['precision']} | {m['faithfulness']} | {m['answer_relevance']} | {m['llm_judge']} |")
    md.append("")
    md.append(f"**汇总**：平均 Recall {report['summary']['avg_recall']}，Faithfulness {report['summary']['avg_faithfulness']}，AnswerRel {report['summary']['avg_answer_relevance']}，LLM-Judge {report['summary']['avg_llm_judge']}。")
    md.append("")
    md.append("> 说明：当前为 Mock/规则基线，接入 DeepSeek 与真实评测集后可复现更严格指标。")
    (root / "docs" / "eval_report.md").write_text("\n".join(md), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
