"""Notebook owner/editor/viewer/guest HTTP behavior and facade ingestion."""
import asyncio
import json
import os
from pathlib import Path
from unittest.mock import patch

import httpx
import server as s

BASE_URL = "http://testserver"
ORIGIN = BASE_URL


async def _new_user(client, prefix):
    username = f"{prefix}-{os.urandom(5).hex()}"
    password = "test-password-123"
    response = await client.post("/api/auth/register", headers={"origin": ORIGIN}, json={"username": username, "password": password})
    assert response.status_code == 201, response.text
    login = await client.post("/api/auth/login", headers={"origin": ORIGIN}, json={"username": username, "password": password})
    assert login.status_code == 200, login.text
    return response.json()["user"]


def test_guest_model_is_limited_to_admins_active_provider_and_per_request():
    async def scenario():
        calls = []
        async def fake_run(ctx, question, notebook_ids, **kwargs):
            calls.append(kwargs)
            return "answer"
        with patch.object(s.runtime, "get_model_settings", return_value={"provider_id": "mock", "model_id": "mock"}), \
             patch.object(s.runtime, "list_models", return_value=[{"id": "mock", "name": "Mock"}, {"id": "mock-alt", "name": "Mock Alt"}]), \
             patch.object(s.runtime, "run", new=fake_run):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=s.app), base_url=BASE_URL) as guest:
                catalog = await guest.get("/api/models/guest")
                assert catalog.status_code == 200, catalog.text
                assert catalog.json()["provider_id"] == "mock"
                assert [item["id"] for item in catalog.json()["models"]] == ["mock", "mock-alt"]
                before = (await guest.get("/api/llm/config")).json()["quota"]["remaining"]
                forbidden_provider = await guest.post("/api/chat", headers={"origin": ORIGIN}, json={
                    "message": "provider override", "knowledge_base_ids": [s.DEMO_KB_ID],
                    "provider_id": "deepseek",
                })
                assert forbidden_provider.status_code == 422, forbidden_provider.text
                switched = await guest.post("/api/chat", headers={"origin": ORIGIN}, json={
                    "message": "stale", "knowledge_base_ids": [s.DEMO_KB_ID],
                    "model_id": "mock-alt", "catalog_provider_id": "deepseek",
                })
                assert switched.status_code == 409, switched.text
                unknown = await guest.post("/api/chat", headers={"origin": ORIGIN}, json={
                    "message": "invalid", "knowledge_base_ids": [s.DEMO_KB_ID],
                    "model_id": "paid-or-unknown", "catalog_provider_id": "mock",
                })
                assert unknown.status_code == 422, unknown.text
                assert (await guest.get("/api/llm/config")).json()["quota"]["remaining"] == before
                response = await guest.post("/api/chat", headers={"origin": ORIGIN}, json={
                    "message": "valid", "knowledge_base_ids": [s.DEMO_KB_ID],
                    "model_id": "mock-alt", "catalog_provider_id": "mock",
                })
                assert response.status_code == 200, response.text
                assert calls == [{"allow_write_tools": False, "model_id": "mock-alt", "expected_provider_id": "mock", "history": None, "memory_enabled": False}]
                assert response.json()["quota"]["remaining"] == before - 1
    asyncio.run(scenario())


def test_owner_editor_viewer_guest_sharing_ingestion_and_conversations():
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=s.app), base_url=BASE_URL) as owner, \
                   httpx.AsyncClient(transport=httpx.ASGITransport(app=s.app), base_url=BASE_URL) as editor, \
                   httpx.AsyncClient(transport=httpx.ASGITransport(app=s.app), base_url=BASE_URL) as viewer, \
                   httpx.AsyncClient(transport=httpx.ASGITransport(app=s.app), base_url=BASE_URL) as guest:
            owner_user = await _new_user(owner, "owner")
            editor_user = await _new_user(editor, "editor")
            viewer_user = await _new_user(viewer, "viewer")
            created = await owner.post("/api/notebooks", headers={"origin": ORIGIN}, json={"name": "权限测试笔记本"})
            assert created.status_code == 201, created.text
            notebook = created.json()
            notebook_id = notebook["id"]
            assert notebook["is_owner"] is True and "role" not in notebook
            for user_id, role in ((editor_user["id"], "editor"), (viewer_user["id"], "viewer"), ("guest", "viewer")):
                response = await owner.put(f"/api/notebooks/{notebook_id}/members/{user_id}", headers={"origin": ORIGIN}, json={"role": role})
                assert response.status_code == 200, response.text
            members = await owner.get(f"/api/notebooks/{notebook_id}/members")
            assert members.status_code == 200
            assert {item["role"] for item in members.json()["members"]} == {"editor", "viewer"}
            assert (await editor.get(f"/api/notebooks/{notebook_id}/members")).status_code == 403
            assert (await editor.put(f"/api/notebooks/{notebook_id}/members/{viewer_user['id']}", headers={"origin": ORIGIN}, json={"role": "editor"})).status_code == 403
            assert (await viewer.get(f"/api/notebooks/{notebook_id}/documents")).status_code == 200
            assert (await viewer.get("/api/notebooks")).json()["notebooks"]
            denied_upload = await viewer.post(f"/api/notebooks/{notebook_id}/files", headers={"origin": ORIGIN}, files={"files": ("readme.txt", b"not allowed", "text/plain")})
            assert denied_upload.status_code == 403
            assert (await guest.get("/api/notebooks/" + notebook_id + "/documents")).status_code == 200
            denied_guest_upload = await guest.post(f"/api/notebooks/{notebook_id}/files", headers={"origin": ORIGIN}, files={"files": ("readme.txt", b"not allowed", "text/plain")})
            assert denied_guest_upload.status_code == 403

            original_ingest = s.rag_service.ingest
            calls = []
            def tracked_ingest(ctx, path, knowledge_base_id, source_id="", progress=None):
                temp_path = Path(path)
                calls.append((str(temp_path), temp_path.exists(), temp_path.read_text(encoding="utf-8"), knowledge_base_id, source_id))
                return original_ingest(ctx, path, knowledge_base_id, source_id, progress)
            with patch.object(s.rag_service, "ingest", side_effect=tracked_ingest):
                uploaded = await editor.post(f"/api/notebooks/{notebook_id}/files?upload_id=ingest-{os.urandom(4).hex()}", headers={"origin": ORIGIN}, files={"files": ("资料\u002eTXT", b"RAG facade ingestion content.", "text/plain")})
            assert uploaded.status_code == 201, uploaded.text
            assert len(calls) == 1 and calls[0][1] and calls[0][2] == "RAG facade ingestion content."
            assert calls[0][3] == notebook_id and calls[0][4] == uploaded.json()["imported"][0]["source_id"]
            assert not Path(calls[0][0]).exists(), "temporary upload must be removed after facade ingestion"
            docs = await editor.get(f"/api/notebooks/{notebook_id}/documents")
            assert uploaded.json()["imported"][0]["source_id"] in {item["source_id"] for item in docs.json()["documents"]}
            forbidden_extension = await editor.post(f"/api/notebooks/{notebook_id}/files", headers={"origin": ORIGIN}, files={"files": ("unsafe.exe", b"x", "application/octet-stream")})
            assert forbidden_extension.status_code == 415
            oversized = await editor.post(f"/api/notebooks/{notebook_id}/files", headers={"origin": ORIGIN}, files={"files": ("large.txt", b"x" * (s.MAX_UPLOAD_BYTES + 1), "text/plain")})
            assert oversized.status_code == 413

            async def fake_run(ctx, question, notebook_ids, **kwargs):
                return "mocked answer"
            with patch.object(s.runtime, "run", new=fake_run):
                guest_chat = await guest.post("/api/chat", headers={"origin": ORIGIN}, json={"message": "guest question", "knowledge_base_ids": [notebook_id]})
                assert guest_chat.status_code == 200, guest_chat.text
                assert guest_chat.json()["conversation_id"] is None
                guest_id = s.auth_service.guest(s.BOOT_CONTEXT).user_id
                assert s.data_service.list_conversations(s._ctx(user_id=guest_id), guest_id, None) == []
                user_chat = await editor.post("/api/chat", headers={"origin": ORIGIN}, json={"message": "user question", "knowledge_base_ids": [notebook_id]})
                assert user_chat.status_code == 200, user_chat.text
                conversation_id = user_chat.json()["conversation_id"]
                persisted = await editor.get(f"/api/conversations/{conversation_id}")
                assert persisted.status_code == 200
                assert [message["role"] for message in persisted.json()["conversation"]["messages"]] == ["user", "assistant"]
            assert (await owner.delete(f"/api/notebooks/{notebook_id}/members/{viewer_user['id']}", headers={"origin": "https://attacker.test"})).status_code == 403
    asyncio.run(scenario())
