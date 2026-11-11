#!/usr/bin/env python3
"""Compare character, token-approximate and structural chunking.

Measures retrieval quality, evidence-span intactness, chunk count, build time
and process peak RSS. It does not call an LLM.
"""
from __future__ import annotations

import argparse
import json
import os
import resource
import statistics
import sys
import time
from pathlib import Path
from typing import Callable, Dict, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments"))

from ingestion import chunk, chunk_structural, chunk_tokens, parse  # noqa: E402
from rag_core import make_embed  # noqa: E402

from run_retrieval import _aggregate, _build_stores, _documents, _evaluate_question  # noqa: E402

CONFIGURATIONS = (
    ("char-500-50", "char", 500, 50),
    ("char-300-30", "char", 300, 30),
    ("token-256-32", "token", 256, 32),
    ("token-512-64", "token", 512, 64),
    ("structural-256-32", "structural", 256, 32),
    ("structural-512-64", "structural", 512, 64),
)
STRATEGIES = ("vector", "keyword", "hybrid", "bm25_hybrid")


def _chunker(strategy: str, size: int, overlap: int) -> Callable[[List[str]], List[str]]:
    if strategy == "char":
        return lambda texts: chunk(texts, size=size, overlap=overlap)
    if strategy == "token":
        return lambda texts: chunk_tokens(texts, size=size, overlap=overlap)
    if strategy == "structural":
        return lambda texts: chunk_structural(texts, size=size, overlap=overlap)
    raise ValueError(strategy)


def _evidence_intact_rate(
    questions: List[dict],
    chunks_by_source: Dict[str, List[str]],
    docs_by_name: Dict[str, str],
) -> float:
    spans = [
        (item["document"], item["text"])
        for question in questions
        for item in question.get("evidence", [])
    ]
    if not spans:
        return 0.0
    intact = 0
    for document, text in spans:
        source_id = "cmrc2018-demo/" + Path(docs_by_name[document]).stem
        if any(text in chunk_text for chunk_text in chunks_by_source.get(source_id, [])):
            intact += 1
    return round(intact / len(spans), 4)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--qa", default=str(ROOT / "experiments" / "qa_set.json"))
    parser.add_argument("--docs", default=str(ROOT / "data" / "kb" / "cmrc2018-demo" / "knowledge-documents"))
    parser.add_argument("--backend", choices=("fastembed", "hash"), default="fastembed")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    os.environ["RAG_EMBED"] = args.backend

    qa = json.loads(Path(args.qa).read_text(encoding="utf-8"))
    docs = _documents(Path(args.docs))
    docs_by_name = {filename: filename for filename, _path in docs}
    embed_fn = make_embed(args.backend)
    rows = []
    for label, strategy, size, overlap in CONFIGURATIONS:
        started = time.perf_counter()
        store, chunks_by_source = _build_stores(docs, _chunker(strategy, size, overlap), embed_fn)
        build_seconds = round(time.perf_counter() - started, 3)
        chunk_count = sum(
            len(chunks) for source, chunks in chunks_by_source.items() if source.startswith("cmrc2018-demo/")
        )
        evaluation_rows = []
        for question in qa["questions"]:
            for retrieval in STRATEGIES:
                row = _evaluate_question(question, retrieval, store, args.top_k, embed_fn)
                row["id"] = question["id"]
                row["question"] = question["question"]
                evaluation_rows.append(row)
        aggregates = {
            retrieval: _aggregate([row for row in evaluation_rows if row["strategy"] == retrieval])
            for retrieval in STRATEGIES
        }
        rows.append(
            {
                "configuration": label,
                "strategy": strategy,
                "size": size,
                "overlap": overlap,
                "chunk_count": chunk_count,
                "avg_chunk_chars": round(
                    statistics.mean(
                        len(chunk_text)
                        for source, chunks in chunks_by_source.items()
                        if source.startswith("cmrc2018-demo/")
                        for chunk_text in chunks
                    ),
                    1,
                ),
                "build_seconds": build_seconds,
                "max_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1),
                "evidence_intact_rate": _evidence_intact_rate(qa["questions"], chunks_by_source, docs_by_name),
                "retrieval": aggregates,
            }
        )
        print(json.dumps({"configuration": label, "chunk_count": chunk_count,
                          "build_seconds": build_seconds}, ensure_ascii=False), flush=True)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "qa_set": qa["name"],
                "backend": args.backend,
                "top_k": args.top_k,
                "document_count": len(docs),
                "configurations": rows,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"output": str(output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
