"""验收：确认集成侧运行时完全由 artifacts 里的编译产物驱动。

运行：
    python scripts/verify_compiled_runtime.py

脚本复用 apps/agent-server 的运行边界，只从 registry.json 指向的已发布 artifacts
解析业务模块；任何模块若从 modules-src 加载，直接失败。
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "apps" / "agent-server"))

import runtime_boundary  # noqa: E402

PUBLISHED = runtime_boundary.enforce_binary_runtime()

from agent_runtime import AgentRuntime  # noqa: E402
from core_contracts import RequestContext  # noqa: E402
from llm_gateway import MockProvider  # noqa: E402
from memory import make_memory  # noqa: E402
from observability import make_trace_store  # noqa: E402
from rag_core import InMemoryVectorStore, embed  # noqa: E402
from rag_tools import RagTools  # noqa: E402
from skill_runtime import SkillRegistry  # noqa: E402
from tool_runtime import ToolRegistry  # noqa: E402

runtime_boundary.assert_binary_runtime(PUBLISHED)

EXPECTED_TOOLS = {
    "search_knowledge_base",
    "hybrid_search_knowledge_base",
    "keyword_search_knowledge_base",
    "list_knowledge_documents",
    "read_knowledge_document",
}

KNOWLEDGE_BASE_ID = "engineering-notebook"


def main() -> None:
    store = InMemoryVectorStore()
    chunks = ["API 认证需要 Bearer token", "网关 keep-alive 超时 SOP"]
    store.add(f"{KNOWLEDGE_BASE_ID}/api-doc", chunks, embed(chunks))

    tracing = make_trace_store()
    rag_tools = RagTools(store, tracing)

    definitions = rag_tools.tool_definitions()
    names = {definition.name for definition in definitions}
    assert names == EXPECTED_TOOLS, names

    tools = ToolRegistry()
    handlers = {
        "search_knowledge_base": lambda query, top_k=None, *, ctx, runtime_context: rag_tools.search(
            ctx, query, runtime_context["knowledge_base_ids"], top_k
        ),
        "hybrid_search_knowledge_base": lambda query, top_k=None, *, ctx, runtime_context: rag_tools.hybrid_search(
            ctx, query, runtime_context["knowledge_base_ids"], top_k
        ),
        "keyword_search_knowledge_base": lambda query, top_k=None, *, ctx, runtime_context: rag_tools.keyword_search(
            ctx, query, runtime_context["knowledge_base_ids"], top_k
        ),
        "list_knowledge_documents": lambda *, ctx, runtime_context: rag_tools.list_documents(
            ctx, runtime_context["knowledge_base_ids"]
        ),
        "read_knowledge_document": lambda source_id, *, ctx, runtime_context: rag_tools.read_document(
            ctx, source_id, runtime_context["knowledge_base_ids"]
        ),
    }
    for definition in definitions:
        tools.register(definition, handlers[definition.name], context_aware=True)

    # 记忆库用内存模式：SQLite 连接不提供 close()，落盘文件在 Windows 上会让
    # 临时目录清理失败（WinError 32）。
    runtime = AgentRuntime(
        provider=MockProvider("qa"),
        memory=make_memory(":memory:"),
        tools=tools,
        skills=SkillRegistry(),
        tracing=tracing,
    )
    answer = asyncio.run(
        runtime.run(
            RequestContext("t", "r", "u", "s"),
            "请查询 API 如何认证？",
            [KNOWLEDGE_BASE_ID],
        )
    )

    assert "api-doc" in answer, answer
    rag_spans = [event for event in tracing.get("t") if event.span == "rag"]
    assert rag_spans, "没有记录到 rag span"
    assert rag_spans[0].meta.get("tool") == "search_knowledge_base", rag_spans[0].meta

    print(
        "modules loaded from:",
        json.dumps({k: str(v["extension"]) for k, v in PUBLISHED.items()}, ensure_ascii=False, indent=2),
    )
    print("rag span meta:", json.dumps(rag_spans[0].meta, ensure_ascii=False))
    print("COMPILED_AGENT_OK")


if __name__ == "__main__":
    main()
