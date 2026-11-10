#!/usr/bin/env python3
"""Small in-memory graph retrieval experiment vs vector retrieval.

The data is synthetic service-dependency text in ``graph_data.json``. The graph
is built in memory only; no production database or graph service is added.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections import deque
from pathlib import Path
from typing import Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
from rag_core import InMemoryVectorStore, make_embed  # noqa: E402


def _vector_documents(edges: List[dict], embed_fn) -> InMemoryVectorStore:
    store = InMemoryVectorStore()
    for edge in edges:
        store.add(edge["from"], [edge["text"]], embed_fn([edge["text"]]))
    return store


def _graph_retrieve(
    question: str,
    nodes: Dict[str, dict],
    edges: List[dict],
    top_k: int,
    max_hops: int = 2,
) -> Tuple[List[str], List[List[str]]]:
    seeds = [node_id for node_id, node in nodes.items() if node["name"] in question]
    if not seeds:
        return [], []
    adjacency: Dict[str, List[Tuple[str, dict]]] = {}
    for edge in edges:
        adjacency.setdefault(edge["from"], []).append((edge["to"], edge))
        adjacency.setdefault(edge["to"], []).append((edge["from"], edge))
    visited = set(seeds)
    queue = deque((seed, [seed]) for seed in seeds)
    documents: List[str] = []
    paths: List[List[str]] = []
    while queue:
        node_id, path = queue.popleft()
        if len(path) - 1 >= max_hops:
            continue
        for neighbor, edge in adjacency.get(node_id, []):
            if edge["text"] not in documents:
                documents.append(edge["text"])
                paths.append(path + [neighbor])
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append((neighbor, path + [neighbor]))
    return documents[:top_k], paths[:top_k]


def _entity_recall(texts: List[str], entities: List[str]) -> float:
    if not entities:
        return 0.0
    joined = "\n".join(texts)
    return round(sum(1 for entity in entities if entity in joined) / len(entities), 4)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default=str(ROOT / "experiments" / "graph_data.json"))
    parser.add_argument("--backend", choices=("fastembed", "hash"), default="fastembed")
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    data = json.loads(Path(args.data).read_text(encoding="utf-8"))
    nodes = {node["id"]: node for node in data["nodes"]}
    edges = data["edges"]
    embed_fn = make_embed(args.backend)
    store = _vector_documents(edges, embed_fn)

    rows = []
    for question in data["questions"]:
        started = time.perf_counter()
        vector_hits = store.search(embed_fn([question["question"]])[0], args.top_k, None)
        vector_latency = round((time.perf_counter() - started) * 1000, 3)
        vector_texts = [text for _source, text, _score in vector_hits]

        started = time.perf_counter()
        graph_texts, paths = _graph_retrieve(question["question"], nodes, edges, args.top_k)
        graph_latency = round((time.perf_counter() - started) * 1000, 3)

        rows.append(
            {
                "id": question["id"],
                "question": question["question"],
                "answer_entities": question["answer_entities"],
                "vector": {
                    "texts": vector_texts,
                    "entity_recall": _entity_recall(vector_texts, question["answer_entities"]),
                    "latency_ms": vector_latency,
                },
                "graph": {
                    "texts": graph_texts,
                    "paths": paths,
                    "entity_recall": _entity_recall(graph_texts, question["answer_entities"]),
                    "latency_ms": graph_latency,
                },
            }
        )

    summary = {
        "questions": len(rows),
        "vector_mean_entity_recall": round(statistics.mean(row["vector"]["entity_recall"] for row in rows), 4),
        "graph_mean_entity_recall": round(statistics.mean(row["graph"]["entity_recall"] for row in rows), 4),
        "vector_mean_latency_ms": round(statistics.mean(row["vector"]["latency_ms"] for row in rows), 3),
        "graph_mean_latency_ms": round(statistics.mean(row["graph"]["latency_ms"] for row in rows), 3),
        "note": "合成数据、8 个问题、内存图；只证明该小实验中的行为，不代表生产图数据库选型。",
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {"backend": args.backend, "top_k": args.top_k, "summary": summary, "rows": rows},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"output": str(output), **summary}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
