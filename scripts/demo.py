from __future__ import annotations

import asyncio
import os
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "apps", "agent-server"))

from app import runtime  # noqa: E402
from core_contracts import RequestContext  # noqa: E402

SCENARIOS = [
    "XX API 如何认证？",
    "昨天的故障跟历史哪次最像？",
    "帮我按照公司的 Bug 流程分析一下这个故障",
    "帮我建立一个 P1 Bug",
    "看看最近有没有相关 commit",
    "我上次处理这个问题做到哪里了？",
]


async def main() -> None:
    for q in SCENARIOS:
        ctx = RequestContext(trace_id=uuid.uuid4().hex, request_id=uuid.uuid4().hex, user_id="u", session_id="s1")
        ans = await runtime.run(ctx, q)
        print(f"Q: {q}\nA: {ans}\n")


if __name__ == "__main__":
    asyncio.run(main())
