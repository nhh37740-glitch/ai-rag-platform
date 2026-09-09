from __future__ import annotations

import os

from mcp_servers.github import build_github_server

REPO = os.environ.get("MCP_GITHUB_REPO", "octocat/Hello-World")


def main() -> None:
    token = os.environ.get("GITHUB_TOKEN", "")
    s = build_github_server(repo=REPO, token=token)
    print("tools:", [t["name"] for t in s.tools()])
    commits = s.call("get_commits", {"per_page": 3})
    print("commits:", commits)
    issues = s.call("list_issues", {"state": "open"})
    print("issues:", issues)


if __name__ == "__main__":
    main()
