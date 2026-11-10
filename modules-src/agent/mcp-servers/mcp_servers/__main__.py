from __future__ import annotations

import json
import os
import sys

from mcp_servers import build_default_server
from mcp_servers.github import build_github_server


def main() -> int:
    """精简的 stdio MCP 服务：从 stdin 读 JSON 行，返回 JSON 响应。"""
    repo = os.environ.get("MCP_GITHUB_REPO", "")
    server = build_github_server(repo=repo, token=os.environ.get("GITHUB_TOKEN", "")) if repo else build_default_server()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        method = req.get("method", "")
        if method == "tools/list":
            out = {"tools": server.tools()}
        elif method == "tools/call":
            p = req.get("params", {})
            out = server.call(p.get("name", ""), p.get("arguments", {}))
        else:
            out = {"error": "unsupported method"}
        sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
