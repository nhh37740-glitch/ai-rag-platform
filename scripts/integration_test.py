from __future__ import annotations

import os
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "apps", "agent-server"))

from app import runtime  # noqa: E402
from core_contracts import RequestContext  # noqa: E402


async def main() -> None:
    # 上传文档→索引→提问（RAG + 工具 + 记忆 端到端）
    ctx = RequestContext(trace_id=uuid.uuid4().hex, request_id=uuid.uuid4().hex, user_id="u", session_id="s1")
    ans = await runtime.run(ctx, "XX API 如何认证？")
    assert "Authorization" in ans, ans
    print("E2E OK:", ans)
    events = runtime.tracing.get(ctx.trace_id)
    print("trace spans:", [e.span for e in events])


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
