#!/usr/bin/env python3
"""Minimal LlamaIndex PoC over the same CMRC documents.

This is an offline comparison, not a production migration. It records whether
the dependency could be imported, development surface, retrieval latency and
quality on a small question subset. If LlamaIndex is unavailable, the result
file says so instead of inventing numbers.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import resource
import statistics
import sys
import time
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments"))

from evaluation import ranking_metrics  # noqa: E402
from ingestion import chunk, parse  # noqa: E402
from rag_core import InMemoryVectorStore, make_embed  # noqa: E402

FRAMEWORK = "llama-index-core"


def _documents(docs_dir: Path) -> List[tuple[str, List[str]]]:
    result = []
    for path in sorted(docs_dir.glob("*.md")):
        chunks = chunk(parse(str(path)))
        if chunks:
            result.append((path.name, chunks))
    return result


def _ranked_docs(texts: List[str], document_chunks: dict[str, List[str]]) -> List[str]:
    ranked = []
    seen = set()
    for text in texts:
        for filename, chunks in document_chunks.items():
            if filename in seen:
                continue
            if text in chunks:
                ranked.append(filename)
                seen.add(filename)
                break
    return ranked


def _evaluate(rows: List[dict], key: str, question: dict) -> None:
    relevant = sorted({Path(item["document"]).name for item in question["evidence"]})
    rows.append(ranking_metrics(relevant, key, k=5))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--qa", default=str(ROOT / "experiments" / "qa_set.json"))
    parser.add_argument("--docs", default=str(ROOT / "data" / "kb" / "cmrc2018-demo" / "knowledge-documents"))
    parser.add_argument("--backend", choices=("fastembed", "hash"), default="fastembed")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    qa = json.loads(Path(args.qa).read_text(encoding="utf-8"))
    questions = [item for item in qa["questions"] if item.get("answerable")][: args.limit]
    documents = _documents(Path(args.docs))
    document_chunks = dict(documents)
    embed_fn = make_embed(args.backend)
    run_started = time.perf_counter()

    try:
        from llama_index.core import Document, Settings, VectorStoreIndex
        from llama_index.core.embeddings import BaseEmbedding
    except ImportError as exc:
        result = {
            "framework": FRAMEWORK,
            "status": "unavailable",
            "reason": type(exc).__name__,
            "note": "未安装 LlamaIndex；没有运行就不记录任何效果数字。",
        }
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False))
        return 0

    class ProjectEmbedding(BaseEmbedding):
        def _get_query_embedding(self, query: str) -> List[float]:
            return embed_fn([query])[0]

        async def _aget_query_embedding(self, query: str) -> List[float]:
            return await asyncio.to_thread(self._get_query_embedding, query)

        def _get_text_embedding(self, text: str) -> List[float]:
            return embed_fn([text])[0]

        async def _aget_text_embedding(self, text: str) -> List[float]:
            return await asyncio.to_thread(self._get_text_embedding, text)

    Settings.embed_model = ProjectEmbedding()
    nodes = [
        Document(text=chunk_text, metadata={"file_name": filename})
        for filename, chunks in documents
        for chunk_text in chunks
    ]
    index = VectorStoreIndex.from_documents(nodes, embed_model=Settings.embed_model)
    retriever = index.as_retriever(similarity_top_k=5)

    # Baseline: the project's own in-memory exact-search path with the same chunks.
    baseline = InMemoryVectorStore()
    for filename, chunks in documents:
        baseline.add(filename, chunks, embed_fn(chunks))

    framework_metrics = []
    baseline_metrics = []
    framework_latencies = []
    baseline_latencies = []
    rows = []
    for question in questions:
        started = time.perf_counter()
        retrieved = retriever.retrieve(question["question"])
        framework_latency = round((time.perf_counter() - started) * 1000, 3)
        framework_latencies.append(framework_latency)
        framework_docs = _ranked_docs([item.get_content() for item in retrieved], document_chunks)
        _evaluate(framework_metrics, framework_docs, question)

        started = time.perf_counter()
        hits = baseline.search(embed_fn([question["question"]])[0], 5, None)
        baseline_latency = round((time.perf_counter() - started) * 1000, 3)
        baseline_latencies.append(baseline_latency)
        baseline_docs = _ranked_docs([text for _source, text, _score in hits], document_chunks)
        _evaluate(baseline_metrics, baseline_docs, question)

        rows.append(
            {
                "id": question["id"],
                "question": question["question"],
                "framework_docs": framework_docs,
                "baseline_docs": baseline_docs,
                "framework_latency_ms": framework_latency,
                "baseline_latency_ms": baseline_latency,
            }
        )

    def mean(metrics: List[dict], key: str) -> float:
        return round(statistics.mean(item[key] for item in metrics), 4) if metrics else 0.0

    result = {
        "framework": FRAMEWORK,
        "status": "ran",
        "backend": args.backend,
        "questions": len(questions),
        "development_surface": {
            "script_lines": len(Path(__file__).read_text(encoding="utf-8").splitlines()),
            "new_dependencies": [FRAMEWORK],
            "production_changes": "none",
        },
        "framework_metrics": {
            "mean_recall_at_k": mean(framework_metrics, "recall_at_k"),
            "mean_mrr_at_k": mean(framework_metrics, "mrr_at_k"),
            "mean_latency_ms": round(statistics.mean(framework_latencies), 3),
        },
        "baseline": {
            "mean_recall_at_k": mean(baseline_metrics, "recall_at_k"),
            "mean_mrr_at_k": mean(baseline_metrics, "mrr_at_k"),
            "mean_latency_ms": round(statistics.mean(baseline_latencies), 3),
        },
        "elapsed_seconds": round(time.perf_counter() - run_started, 3),
        "max_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1),
        "note": "最小 PoC；未接入生产，不代表框架整体优劣。",
        "rows": rows,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "status": "ran"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
