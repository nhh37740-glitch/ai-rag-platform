"""Public access is the guest view of the same RAGnotebook app."""
import asyncio

import httpx
import server as s

BASE_URL = "http://testserver"


def test_guest_uses_single_app_and_only_reads_shared_cmrc_notebook():
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=s.app), base_url=BASE_URL) as client:
            root = await client.get("/")
            assert root.status_code == 200 and "RAGnotebook" in root.text
            identity = await client.get("/api/auth/session")
            assert identity.status_code == 200
            assert identity.json()["role"] == "guest" and identity.json()["read_only"] is True
            notebooks = await client.get("/api/notebooks")
            assert notebooks.status_code == 200
            assert s.DEMO_KB_ID in {item["id"] for item in notebooks.json()["notebooks"]}
            documents = await client.get(f"/api/notebooks/{s.DEMO_KB_ID}/documents")
            assert documents.status_code == 200 and documents.json()["writable"] is False
            assert len(documents.json()["documents"]) == 24
            info = await client.get("/api/demo")
            assert info.status_code == 200
            assert info.json()["question_count"] == 99
            assert info.json()["public_demo"] is s.PUBLIC_DEMO and info.json()["read_only"] is s.PUBLIC_DEMO
            assert (await client.get("/api/admin/users")).status_code == 403
            assert (await client.get("/api/models/providers")).status_code == 403
            assert (await client.post("/api/demo/chat", json={"question": "legacy"})).status_code == 404
            denied = await client.post("/api/notebooks", headers={"origin": BASE_URL}, json={"name": "guest cannot create"})
            assert denied.status_code == 403
    asyncio.run(scenario())
