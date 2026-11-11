#!/usr/bin/env python3
"""Compare retrieval strategies on the curated 60-question CMRC set.

Run inside the project's Python 3.11 environment (or the prepared container):

    python experiments/run_retrieval.py --backend fastembed \
        --output experiments/results/retrieval-fastembed.json

The script never calls an LLM. It measures retrieval only, so results are
independent of whether a real generation model is configured.
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
from typing import Callable, Dict, List, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments"))

from ingestion import chunk, chunk_tokens, parse  # noqa: E402
from rag_core import (  # noqa: E402
    InMemoryVectorStore,
    bm25_hybrid_search,
    bm25_search,
    hybrid_search,
    keyword_search,
    make_embed,
    rerank_by_lexical_overlap,
)
from evaluation import ranking_metrics  # noqa: E402

STRATEGIES = ("vector", "keyword", "hybrid", "bm25", "bm25_hybrid", "rerank")
RESTRICTED_DOCUMENTS = ("008-静电感应.md", "017-魔弹理论.md", "024-海军十字勋章.md")


def _documents(docs_dir: Path) -> List[Tuple[str, Path]]:
    return sorted((path.name, path) for path in docs_dir.glob("*.md"))


def _build_stores(
    docs: Sequence[Tuple[str, Path]],
    chunker: Callable[[List[str]], List[str]],
    embed_fn: Callable[[List[str]], List[List[float]]],
) -> Tuple[InMemoryVectorStore, Dict[str, List[str]]]:
    store = InMemoryVectorStore()
    chunks_by_source: Dict[str, List[str]] = {}
    vectors_by_file: Dict[str, List[List[float]]] = {}
    for filename, path in docs:
        texts = parse(str(path))
        chunks = chunker(texts)
        if not chunks:
            continue
        vectors = embed_fn(chunks)
        source_id = "cmrc2018-demo/" + Path(filename).stem
        store.add(source_id, chunks, vectors)
        chunks_by_source[source_id] = chunks
        vectors_by_file[filename] = vectors
    for filename in RESTRICTED_DOCUMENTS:
        source_id = "restricted-kb/" + Path(filename).stem
        chunks = chunks_by_source["cmrc2018-demo/" + Path(filename).stem]
        store.add(source_id, chunks, vectors_by_file[filename])
        chunks_by_source[source_id] = chunks
    return store, chunks_by_source


def _hits_from_result(result) -> List[Tuple[str, str, float]]:
    return [(citation.source_id, citation.text, citation.score) for citation in result.citations]


def _retrieve(
    strategy: str,
    query: str,
    store: InMemoryVectorStore,
    scope: List[str],
    top_k: int,
    embed_fn: Callable[[List[str]], List[List[float]]],
) -> List[Tuple[str, str, float]]:
    if strategy == "vector":
        return store.search(embed_fn([query])[0], top_k, scope)
    if strategy == "keyword":
        return _hits_from_result(keyword_search(None, query, store, scope=scope, top_k=top_k))
    if strategy == "hybrid":
        return _hits_from_result(hybrid_search(None, query, store, scope=scope, top_k=top_k))
    if strategy == "bm25":
        return _hits_from_result(bm25_search(None, query, store, scope=scope, top_k=top_k))
    if strategy == "bm25_hybrid":
        return _hits_from_result(bm25_hybrid_search(None, query, store, scope=scope, top_k=top_k))
    if strategy == "rerank":
        candidates = store.search(embed_fn([query])[0], max(top_k * 4, 20), scope)
        return rerank_by_lexical_overlap(query, candidates, top_k=top_k, weight=0.5)
    raise ValueError(f"unknown strategy: {strategy}")


def _ranked_documents(hits: Sequence[Tuple[str, str, float]]) -> List[str]:
    ranked: List[str] = []
    seen = set()
    for source_id, _text, _score in hits:
        document = Path(source_id).name
        if document not in seen:
            seen.add(document)
            ranked.append(document)
    return ranked


def _evidence_coverage(evidence: Sequence[dict], hits: Sequence[Tuple[str, str, float]]) -> float:
    if not evidence:
        return 0.0
    texts = [text for _source_id, text, _score in hits]
    found = sum(1 for item in evidence if any(item["text"] in text for text in texts))
    return round(found / len(evidence), 4)


def _evaluate_question(
    question: dict,
    strategy: str,
    store: InMemoryVectorStore,
    top_k: int,
    embed_fn: Callable[[List[str]], List[List[float]]],
) -> dict:
    started = time.perf_counter()
    hits = _retrieve(
        strategy,
        question["question"],
        store,
        question.get("scope", ["cmrc2018-demo"]),
        top_k,
        embed_fn,
    )
    latency_ms = round((time.perf_counter() - started) * 1000, 3)
    ranked_documents = _ranked_documents(hits)
    evidence = question.get("evidence", [])
    relevant_documents = sorted({Path(item["document"]).stem for item in evidence})
    metrics = ranking_metrics(relevant_documents, ranked_documents, k=top_k)
    forbidden = {Path(item).stem for item in question.get("forbidden_documents", [])}
    forbidden_hits = [
        source_id for source_id, _text, _score in hits if Path(source_id).name in forbidden
    ]
    return {
        "strategy": strategy,
        "category": question["category"],
        "answerable": bool(question.get("answerable", True)),
        "ranked_documents": ranked_documents,
        "metrics": metrics,
        "evidence_coverage": _evidence_coverage(evidence, hits),
        "hit_count": len(hits),
        "forbidden_hits": forbidden_hits,
        "latency_ms": latency_ms,
    }


def _aggregate(rows: Sequence[dict]) -> dict:
    groups: Dict[str, List[dict]] = {}
    for row in rows:
        groups.setdefault(row["category"], []).append(row)
    result: Dict[str, dict] = {}
    for category, items in sorted(groups.items()):
        answerable = [item for item in items if item["answerable"]]
        result[category] = {
            "questions": len(items),
            "answerable": len(answerable),
            "mean_recall_at_k": round(statistics.mean([item["metrics"]["recall_at_k"] for item in answerable]), 4) if answerable else None,
            "mean_precision_at_k": round(statistics.mean([item["metrics"]["precision_at_k"] for item in answerable]), 4) if answerable else None,
            "mean_mrr_at_k": round(statistics.mean([item["metrics"]["mrr_at_k"] for item in answerable]), 4) if answerable else None,
            "mean_ndcg_at_k": round(statistics.mean([item["metrics"]["ndcg_at_k"] for item in answerable]), 4) if answerable else None,
            "mean_evidence_coverage": round(statistics.mean([item["evidence_coverage"] for item in answerable]), 4) if answerable else None,
            "mean_latency_ms": round(statistics.mean([item["latency_ms"] for item in items]), 3),
            "questions_with_forbidden_hits": sum(1 for item in items if item["forbidden_hits"]),
        }
    answerable = [row for row in rows if row["answerable"]]
    result["_overall"] = {
        "questions": len(rows),
        "answerable": len(answerable),
        "mean_recall_at_k": round(statistics.mean([row["metrics"]["recall_at_k"] for row in answerable]), 4) if answerable else None,
        "mean_precision_at_k": round(statistics.mean([row["metrics"]["precision_at_k"] for row in answerable]), 4) if answerable else None,
        "mean_mrr_at_k": round(statistics.mean([row["metrics"]["mrr_at_k"] for row in answerable]), 4) if answerable else None,
        "mean_ndcg_at_k": round(statistics.mean([row["metrics"]["ndcg_at_k"] for row in answerable]), 4) if answerable else None,
        "mean_evidence_coverage": round(statistics.mean([row["evidence_coverage"] for row in answerable]), 4) if answerable else None,
        "mean_latency_ms": round(statistics.mean([row["latency_ms"] for row in rows]), 3),
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--qa", default=str(ROOT / "experiments" / "qa_set.json"))
    parser.add_argument("--docs", default=str(ROOT / "data" / "kb" / "cmrc2018-demo" / "knowledge-documents"))
    parser.add_argument("--backend", choices=("fastembed", "hash"), default="fastembed")
    parser.add_argument("--chunker", choices=("char", "token"), default="char")
    parser.add_argument("--size", type=int, default=500)
    parser.add_argument("--overlap", type=int, default=50)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    # hybrid_search/bm25_hybrid_search use rag_core.embed() internally; keep
    # every route on the backend selected for this run.
    os.environ["RAG_EMBED"] = args.backend

    qa = json.loads(Path(args.qa).read_text(encoding="utf-8"))
    docs = _documents(Path(args.docs))
    chunker = (
        (lambda texts: chunk(texts, size=args.size, overlap=args.overlap))
        if args.chunker == "char"
        else (lambda texts: chunk_tokens(texts, size=args.size, overlap=args.overlap))
    )
    embed_fn = make_embed(args.backend)
    store, _chunks = _build_stores(docs, chunker, embed_fn)

    started = time.perf_counter()
    per_question = []
    for question in qa["questions"]:
        for strategy in STRATEGIES:
            row = _evaluate_question(question, strategy, store, args.top_k, embed_fn)
            row["id"] = question["id"]
            row["question"] = question["question"]
            per_question.append(row)

    aggregates: Dict[str, dict] = {}
    for strategy in STRATEGIES:
        aggregates[strategy] = _aggregate([row for row in per_question if row["strategy"] == strategy])

    result = {
        "qa_set": qa["name"],
        "qa_version": qa.get("version"),
        "backend": args.backend,
        "chunker": args.chunker,
        "chunk_size": args.size,
        "chunk_overlap": args.overlap,
        "top_k": args.top_k,
        "document_count": len(docs),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "max_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1),
        "strategies": list(STRATEGIES),
        "aggregates": aggregates,
        "per_question": per_question,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "elapsed_seconds": result["elapsed_seconds"],
                      "max_rss_mb": result["max_rss_mb"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
