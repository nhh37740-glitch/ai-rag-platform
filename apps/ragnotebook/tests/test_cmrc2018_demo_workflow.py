"""The bundled CMRC corpus is exposed through the unified HTTP/facade path."""
import asyncio
import json
from pathlib import Path

import httpx
import server as s

BASE_URL = "http://testserver"
ROOT = Path(__file__).resolve().parents[3]


def test_cmrc_manifest_and_guest_http_workflow():
    manifest_path = ROOT / "data" / "kb" / "cmrc2018-demo" / "knowledge-base-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert len(manifest["documents"]) == 24
    assert sum(len(item["questions"]) for item in manifest["documents"]) == 99
    assert all((manifest_path.parent / "knowledge-documents" / item["file"]).is_file() for item in manifest["documents"])

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=s.app), base_url=BASE_URL) as client:
            response = await client.get("/api/demo")
            assert response.status_code == 200
            assert response.json()["id"] == s.DEMO_KB_ID
            assert response.json()["question_count"] == 99
            notebook = await client.get(f"/api/notebooks/{s.DEMO_KB_ID}/suggestions")
            assert notebook.status_code == 200 and notebook.json()["source"] == "curated"
            assert len(notebook.json()["questions"]) == 8
            documents = await client.get(f"/api/notebooks/{s.DEMO_KB_ID}/documents")
            assert documents.status_code == 200 and len(documents.json()["documents"]) == 24
            assert all(item["source_id"].startswith(s.DEMO_KB_ID + "/") for item in documents.json()["documents"])
    asyncio.run(scenario())
