from __future__ import annotations

from typing import Any, Optional

import httpx

from mcp_servers import MockMcpServer


def register_github_connector(
    server: MockMcpServer,
    repo: str = "octocat/Hello-World",
    token: str = "",
    client: Optional[httpx.Client] = None,
) -> None:
    """真实 GitHub 公共 API connector（无 token 可用；token 提升限额/私有仓库）。"""
    base = f"https://api.github.com/repos/{repo}"
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    def _client() -> httpx.Client:
        return client or httpx.Client(timeout=30, headers=headers)

    def get_commits(per_page: int = 5):
        with _client() as c:
            r = c.get(f"{base}/commits", params={"per_page": per_page})
            r.raise_for_status()
            return [{"sha": i["sha"][:8], "message": i["commit"]["message"].splitlines()[0]} for i in r.json()]

    def list_issues(state: str = "open"):
        with _client() as c:
            r = c.get(f"{base}/issues", params={"state": state})
            r.raise_for_status()
            return [{"number": i["number"], "title": i["title"], "state": i["state"]} for i in r.json() if "pull_request" not in i]

    def get_commit(sha: str = ""):
        with _client() as c:
            r = c.get(f"{base}/commits/{sha}")
            r.raise_for_status()
            return {"sha": r.json()["sha"][:8], "message": r.json()["commit"]["message"].splitlines()[0]}

    server.register("get_commits", "查询 GitHub 最近提交", {"type": "object", "properties": {"per_page": {"type": "integer"}}}, get_commits)
    server.register("list_issues", "查询 GitHub issues", {"type": "object", "properties": {"state": {"type": "string"}}}, list_issues)
    server.register("get_commit", "查询某提交详情", {"type": "object", "properties": {"sha": {"type": "string"}}}, get_commit)


def build_github_server(repo: str = "octocat/Hello-World", token: str = "", client: Optional[httpx.Client] = None) -> MockMcpServer:
    server = MockMcpServer()
    register_github_connector(server, repo=repo, token=token, client=client)
    return server


__all__ = ["register_github_connector", "build_github_server"]
