from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "registry.json"

# 只从 registry 指向的已发布 artifacts 解析模块（目录内不含实现源码）。
registry = json.loads(REGISTRY.read_text(encoding="utf-8"))["modules"]
required = ("observability", "memory", "tool-runtime", "skill-runtime", "llm-gateway", "rag-core", "agent-runtime")
missing = [module_id for module_id in required if registry.get(module_id, {}).get("status") != "published"]
if missing:
    raise RuntimeError("compile and package these modules first: " + ", ".join(missing))
for module_id in required:
    sys.path.insert(0, str(ROOT / registry[module_id]["path"]))

from core_contracts import RequestContext, ToolDef  # noqa: E402
from agent_runtime import AgentRuntime  # noqa: E402
from llm_gateway import MockProvider  # noqa: E402
from memory import make_memory  # noqa: E402
from observability import make_trace_store  # noqa: E402
from rag_core import InMemoryVectorStore, embed  # noqa: E402
from skill_runtime import SkillRegistry  # noqa: E402
from tool_runtime import ToolRegistry  # noqa: E402

assert __import__("observability").__file__.endswith(".pyd"), "observability must load from .pyd"

store = InMemoryVectorStore()
chunks = ["API 认证需要 Bearer token", "网关 keep-alive 超时 SOP"]
store.add("doc", chunks, embed(chunks))

tools = ToolRegistry()
tools.register(ToolDef("create_issue", "c", {"type": "object"}), lambda title, priority="P2": f"issue:{title}")

rt = AgentRuntime(
    provider=MockProvider("qa"),
    vector_store=store,
    memory=make_memory("data/_tests/compiled.db"),
    tools=tools,
    skills=SkillRegistry(),
    tracing=make_trace_store(),
)
ans = asyncio.get_event_loop().run_until_complete(rt.run(RequestContext("t", "r", "u", "s"), "API 如何认证？"))
assert "Authorization" in ans, ans
print("imported observability from:", __import__("observability").__file__)
print("compiled modules loaded; answer:", ans)
print("COMPILED_AGENT_OK")
