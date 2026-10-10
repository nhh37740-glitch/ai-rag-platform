"""验证所有编译模块可加载，并用三个中间包执行入库、五个工具和问答。"""
from __future__ import annotations
import asyncio
import importlib
import json
import sys
import tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/agent-server"))
import runtime_boundary
PUBLISHED = runtime_boundary.enforce_binary_runtime()
for package in PUBLISHED:
    importlib.import_module(package)
from core_specifications import RequestContext, ToolCall
from agent_facade import AgentService, make_provider
from data_facade import DataService
from rag_facade import RagService
from observability import make_trace_store
from auth_runtime import AuthService
runtime_boundary.assert_binary_runtime(PUBLISHED)
EXPECTED_TOOLS = {"search_knowledge_base", "hybrid_search_knowledge_base", "keyword_search_knowledge_base", "list_knowledge_documents", "read_knowledge_document"}


def main():
    ctx = RequestContext("compiled-smoke", "request", "user", "session")
    auth = AuthService("compiled-smoke-proxy-proof-32-bytes", "owner")
    guest = auth.guest(ctx)
    auth.authorize(ctx, guest, "query")
    assert auth.allowed_notebooks(ctx, guest, ["private", "public"], ["public"]) == ["public"]
    try:
        auth.authorize(ctx, guest, "create_notebook")
    except PermissionError:
        pass
    else:
        raise AssertionError("guest write was authorized")
    owner = auth.authenticate_proxy(ctx, "compiled-smoke-proxy-proof-32-bytes", "owner", "admin")
    auth.authorize(ctx, owner, "import_document")
    with tempfile.TemporaryDirectory() as temporary:
        data = DataService(temporary)
        tracing = make_trace_store()
        rag = RagService(data.vector_store(ctx), tracing)
        agent = AgentService(data, rag, tracing, str(ROOT / "skills"), make_provider())
        try:
            rag.ingest_markdown(ctx, "# API\n\nAPI 认证需要 Bearer token。", "engineering/api-doc")
            assert {d.name for d in agent.tool_definitions(ctx)} == EXPECTED_TOOLS
            for name in sorted(EXPECTED_TOOLS):
                args = {"query": "API 如何认证？"} if "search" in name else {"source_id": "engineering/api-doc"} if name == "read_knowledge_document" else {}
                result = json.loads(rag.execute_tool(ctx, ToolCall(name, name, args), ["engineering"]))
                assert result.get("hit_count", len(result.get("documents", []))) > 0, (name, result)
            answer = asyncio.run(agent.run(ctx, "请查询 API 如何认证？", ["engineering"]))
            assert "api-doc" in answer, answer
            spans = [e for e in tracing.get(ctx.trace_id) if e.span == "rag"]
            assert EXPECTED_TOOLS <= {e.meta.get("tool") for e in spans}
        finally:
            asyncio.run(agent.aclose(ctx))
            data.close(ctx)
    print("modules loaded from:", json.dumps({k: str(v["extension"]) for k,v in PUBLISHED.items()}, ensure_ascii=False))
    print("COMPILED_AGENT_OK")

if __name__ == "__main__":
    main()
