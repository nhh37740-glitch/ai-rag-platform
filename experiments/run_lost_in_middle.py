#!/usr/bin/env python3
"""Controlled evidence-position experiment (start / middle / end).

The script always builds and saves the exact prompts. With ``--provider mock``
it does not claim a position effect; it records ``quality_conclusion:
unavailable``. With a real provider it calls the configured OpenAI-compatible
endpoint and records model, latency, failures and answer checks.

Never prints or writes the API key.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import List, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments"))

from core_specifications import ChatMessage, RequestContext  # noqa: E402
from ingestion import parse  # noqa: E402
from llm_gateway import DeepSeekProvider, MockProvider  # noqa: E402

POSITIONS = ("start", "middle", "end")
DISTRACTOR_COUNT = 4


def _load_questions(path: Path) -> List[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [
        item for item in data["questions"]
        if item.get("answerable") and item.get("evidence")
    ]


def _chunks_for(path: Path) -> List[str]:
    from ingestion import chunk
    return chunk(parse(str(path)))


def _find_evidence_chunk(chunks: List[str], evidence: str) -> str:
    for text in chunks:
        if evidence in text:
            return text
    return evidence


def _distractors(docs: List[Tuple[str, Path]], exclude: str, limit: int) -> List[str]:
    result: List[str] = []
    for filename, path in docs:
        if filename == exclude:
            continue
        chunks = _chunks_for(path)
        if chunks:
            result.append(chunks[0])
        if len(result) >= limit:
            break
    return result


def _build_prompt(question: str, evidence: str, distractors: List[str], position: str) -> Tuple[str, int]:
    contexts = list(distractors[:DISTRACTOR_COUNT])
    index = {"start": 0, "middle": len(contexts) // 2, "end": len(contexts)}[position]
    contexts.insert(index, evidence)
    lines = [
        "请仅根据下列资料回答问题。资料按编号排列；如果资料不足，请直接说明证据不足。",
        "回答中请用 [n] 标注实际使用的资料编号。",
        "",
    ]
    for number, text in enumerate(contexts, start=1):
        lines.append(f"[{number}] {text}")
    lines.extend(["", f"问题：{question}", "答案："])
    return "\n".join(lines), index + 1


def _answer_checks(answer: str, expected: str, evidence_number: int) -> dict:
    compact = re.sub(r"\s+", "", answer)
    expected_compact = re.sub(r"\s+", "", expected)
    cited = f"[{evidence_number}]" in answer
    return {
        "exact_contains_expected": expected_compact in compact if expected_compact else False,
        "cites_evidence_number": cited,
        "answer_chars": len(answer),
    }


async def _run(args) -> int:
    qa = _load_questions(Path(args.qa))
    if args.limit:
        qa = qa[: args.limit]
    docs = sorted((path.name, path) for path in Path(args.docs).glob("*.md"))
    docs_by_name = dict(docs)
    rows = []
    if args.provider != "mock" and not os.environ.get("OPENROUTER_API_KEY" if args.provider == "openrouter" else "DEEPSEEK_API_KEY", ""):
        raise SystemExit("缺少对应 provider 的服务端密钥；不会用空 key 发起请求")
    provider = MockProvider("qa") if args.provider == "mock" else DeepSeekProvider(
        os.environ.get("OPENROUTER_API_KEY" if args.provider == "openrouter" else "DEEPSEEK_API_KEY", ""),
        base_url="https://openrouter.ai/api/v1" if args.provider == "openrouter" else "https://api.deepseek.com",
        model=args.model,
    )
    for question in qa:
        filename = question["evidence"][0]["document"]
        evidence = question["evidence"][0]["text"]
        chunks = _chunks_for(docs_by_name[filename])
        evidence_chunk = _find_evidence_chunk(chunks, evidence)
        distractors = _distractors(docs, filename, DISTRACTOR_COUNT)
        for position in POSITIONS:
            prompt, evidence_number = _build_prompt(
                question["question"], evidence_chunk, distractors, position
            )
            started = time.perf_counter()
            error = ""
            answer = ""
            try:
                answer, _ = await provider.generate(
                    RequestContext("lost-middle", "request"),
                    [ChatMessage("user", prompt)],
                    None,
                )
            except Exception as exc:  # noqa: BLE001 - failures are recorded, not hidden
                error = type(exc).__name__
            rows.append(
                {
                    "id": question["id"],
                    "position": position,
                    "evidence_number": evidence_number,
                    "prompt": prompt,
                    "answer": answer,
                    "error": error,
                    "latency_ms": round((time.perf_counter() - started) * 1000, 3),
                    "checks": _answer_checks(answer, question["answer"], evidence_number),
                }
            )
    result = {
        "provider": args.provider,
        "model": args.model,
        "status": "mock_not_evidence" if args.provider == "mock" else "real_model_run",
        "quality_conclusion": "unavailable" if args.provider == "mock" else "see per-question checks",
        "note": (
            "Mock 只验证上下文构造与脚本可运行，不能据此声称位置效应。"
            if args.provider == "mock"
            else "结果只对本次模型、提示词和样本成立；失败与延迟一并记录。"
        ),
        "questions": len(qa),
        "positions": list(POSITIONS),
        "rows": rows,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "status": result["status"]}, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--qa", default=str(ROOT / "experiments" / "qa_set.json"))
    parser.add_argument("--docs", default=str(ROOT / "data" / "kb" / "cmrc2018-demo" / "knowledge-documents"))
    parser.add_argument("--provider", choices=("mock", "openrouter", "deepseek"), default="mock")
    parser.add_argument("--model", default="openrouter/free")
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--output", required=True)
    return asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
