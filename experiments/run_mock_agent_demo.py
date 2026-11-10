#!/usr/bin/env python3
"""Offline end-to-end demo: real retrieval + MockProvider generation.

The live server currently has an expired OpenRouter key, so this script shows
the retrieval chain, citations and trace without pretending the Mock answer is
a real model result. It runs entirely in-process and does not touch production.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments"))

from agent_runtime import AgentRuntime  # noqa: E402
from core_specifications import RequestContext, ToolDef  # noqa: E402
from ingestion import chunk, parse  # noqa: E402
from llm_gateway import MockProvider  # noqa: E402
from observability import make_trace_store  # noqa: E402
from rag_core import InMemoryVectorStore, make_embed  # noqa: E402
from rag_tools import RagTools  # noqa: E402
from skill_runtime import SkillRegistry  # noqa: E402
from tool_runtime import ToolRegistry  # noqa: E402


class FakeMemory:
    def __init__(self):
        self.entries = {}

    def get(self, ctx, namespace, key):
        return self.entries.get((ctx.user_id, ctx.session_id, namespace, key))

    def write(self, ctx, namespace, key, content, importance=0.0):
        from core_specifications import MemoryEntry
        entry = MemoryEntry(key, namespace, key, content, "demo", importance)
        self.entries[(ctx.user_id, ctx.session_id, namespace, key)] = entry
        return entry

    def search(self, ctx, namespace, query, top_k=5):
        return []

    def forget(self, ctx, namespace, key):
        self.entries.pop((ctx.user_id, ctx.session_id, namespace, key), None)


def _store(docs_dir: Path, embed_fn):
    store = InMemoryVectorStore()
    for path in sorted(docs_dir.glob("*.md")):
        chunks = chunk(parse(str(path)))
        if chunks:
            store.add("cmrc2018-demo/" + path.stem, chunks, embed_fn(chunks))
    return store


def _register(registry: ToolRegistry, tools: RagTools) -> None:
    def search(query, top_k=None, *, ctx, runtime_context):
        return tools.search(ctx, query, runtime_context["knowledge_base_ids"], top_k)

    def hybrid(query, top_k=None, *, ctx, runtime_context):
        return tools.hybrid_search(ctx, query, runtime_context["knowledge_base_ids"], top_k)

    def keyword(query, top_k=None, *, ctx, runtime_context):
        return tools.keyword_search(ctx, query, runtime_context["knowledge_base_ids"], top_k)

    def listing(*, ctx, runtime_context):
        return tools.list_documents(ctx, runtime_context["knowledge_base_ids"])

    def read(source_id, offset=0, max_chunks=None, *, ctx, runtime_context):
        return tools.read_document(
            ctx, source_id, runtime_context["knowledge_base_ids"], offset=offset, max_chunks=max_chunks
        )

    handlers = {
        "search_knowledge_base": search,
        "hybrid_search_knowledge_base": hybrid,
        "keyword_search_knowledge_base": keyword,
        "list_knowledge_documents": listing,
        "read_knowledge_document": read,
    }
    for definition in tools.tool_definitions():
        registry.register(definition, handlers[definition.name], context_aware=True)


async def _run(question: str, backend: str) -> dict:
    embed_fn = make_embed(backend)
    tracing = make_trace_store()
    tools = RagTools(_store(ROOT / "data" / "kb" / "cmrc2018-demo" / "knowledge-documents", embed_fn), tracing)
    registry = ToolRegistry()
    _register(registry, tools)
    runtime = AgentRuntime(
        provider=MockProvider("qa"),
        memory=FakeMemory(),
        tools=registry,
        skills=SkillRegistry(),
        tracing=tracing,
    )
    ctx = RequestContext("demo-trace", "demo-request", "demo-user", "demo-session")
    answer = await runtime.run(ctx, question, ["cmrc2018-demo"])
    events = tracing.get("demo-trace")
    hits = []
    for event in events:
        if event.span == "rag":
            for hit in (event.meta or {}).get("hits", []):
                hits.append(
                    {
                        "source_id": hit.get("source_id"),
                        "title": hit.get("title"),
                        "score": hit.get("score"),
                        "preview": hit.get("text_preview"),
                    }
                )
    stops = [event.meta for event in events if event.span == "agent_stop"]
    return {
        "provider": "mock",
        "question": question,
        "answer": answer,
        "retrieval_hits": hits,
        "stop_reasons": stops,
        "note": "Mock 生成；只证明检索、引用字段和 trace 链路，不代表自然语言答案质量。",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--question", default="请查资料，什么是静电感应？")
    parser.add_argument("--backend", choices=("fastembed", "hash"), default="fastembed")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = asyncio.run(_run(args.question, args.backend))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
