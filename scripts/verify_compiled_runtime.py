"""验证编译模块边界，以及 RAGnotebook 的单数据库业务闭环。"""
from __future__ import annotations

import asyncio
import importlib
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/ragnotebook"))
import runtime_boundary

PUBLISHED = runtime_boundary.enforce_binary_runtime()
for package in PUBLISHED:
    importlib.import_module(package)

from core_specifications import RequestContext
from agent_facade import AgentService, make_provider
from auth_facade import AuthService
from data_facade import DataService
from rag_facade import RagService

runtime_boundary.assert_binary_runtime(PUBLISHED)


def main():
    with tempfile.TemporaryDirectory() as temporary:
        database_path = str(Path(temporary) / "ragnotebook.sqlite")
        ctx = RequestContext("compiled-smoke", "request")
        data = DataService(database_path)
        auth = AuthService(data)
        auth.initialize(ctx, "bootstrap-admin", "compiled-smoke-password")
        admin, token = auth.login(ctx, "bootstrap-admin", "compiled-smoke-password")
        assert auth.authenticate_session(ctx, token).user_id == admin.user_id
        registered = auth.register(ctx, "compiled-user", "compiled-user-password")
        user, user_token = auth.login(ctx, "compiled-user", "compiled-user-password")
        guest = auth.guest(ctx)

        notebook_id = "compiled-smoke-notebook"
        data.create_notebook(ctx, {"id": notebook_id, "owner_user_id": user.user_id, "name": "Smoke"})
        auth.set_member(ctx, user, notebook_id, "guest", "viewer")
        auth.authorize_notebook(ctx, guest, notebook_id, "read")
        try:
            auth.authorize_notebook(ctx, guest, notebook_id, "write")
        except PermissionError:
            pass
        else:
            raise AssertionError("guest viewer was allowed to write")

        admin_ctx = RequestContext("compiled-admin", "query", admin.user_id)
        assert auth.reserve_query(admin_ctx)["limit"] == 100
        guest_ctx = RequestContext("compiled-guest", "query", "guest")
        assert auth.reserve_query(guest_ctx)["used"] == 2
        auth.set_user_active(ctx, admin, registered["id"], False)
        try:
            auth.authenticate_session(ctx, user_token)  # Disabled accounts cannot reuse an in-memory session.
        except PermissionError:
            pass
        else:
            raise AssertionError("disabled account retained a valid session")

        rag = RagService(data.vector_store(ctx))
        rag.ingest_markdown(ctx, "# API\n\nAPI authentication uses a server-managed session.", f"{notebook_id}/api-doc")
        result = rag.search(ctx, "API authentication", [notebook_id], mode="keyword")
        assert result.citations and result.citations[0].source_id.startswith(notebook_id + "/")

        agent = AgentService(data, rag, skill_dir=str(ROOT / "skills"), provider=make_provider(),
                             environment={"LLM_PROVIDER": "mock"})
        try:
            settings = agent.update_model_settings(ctx, "mock", "mock")
            assert settings["provider_id"] == "mock"
            assert "api_key" not in settings and "key" not in settings
        finally:
            asyncio.run(agent.aclose(ctx))
            data.close(ctx)

        with sqlite3.connect(database_path) as connection:
            tables = {row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )}
        assert tables == {"users", "notebooks", "notebook_members", "documents", "conversations", "agent_data"}, tables
        assert list(Path(temporary).glob("*.sqlite")) == [Path(database_path)]

    print("modules loaded from:", json.dumps({k: str(v["extension"]) for k,v in PUBLISHED.items()}, ensure_ascii=False))
    print("RAGNOTEBOOK_COMPILED_OK")


if __name__ == "__main__":
    main()
