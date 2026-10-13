"""四个验收场景：新用户注册、上传长篇小说、共享给游客、游客用免费模型检索。"""
import asyncio
import os
from unittest.mock import patch

import httpx
import server as s

BASE_URL = "http://testserver"
ORIGIN = BASE_URL
GUEST_USER_ID = "guest"
PASSWORD = "acceptance-password-123"


def _novel(chapters=80, paragraphs=8):
    """生成足够长的中文文本，覆盖「一个文档很多分块」的导入路径。"""
    lines = ["# 银河争霸战", ""]
    for index in range(1, chapters + 1):
        lines.append("## 第 %d 章" % index)
        for paragraph in range(paragraphs):
            lines.append(
                "舰队在猎户座旋臂外侧完成跃迁，指挥官命令护航编队展开扇形阵列，"
                "雷达发现不明信号源，这是第 %d 章第 %d 段例行巡航记录。"
                % (index, paragraph + 1)
            )
        lines.append("")
    return "\n".join(lines).encode("utf-8")


async def _register(client, prefix):
    username = "%s-%s" % (prefix, os.urandom(5).hex())
    created = await client.post(
        "/api/auth/register",
        headers={"origin": ORIGIN},
        json={"username": username, "password": PASSWORD},
    )
    assert created.status_code == 201, created.text
    login = await client.post(
        "/api/auth/login",
        headers={"origin": ORIGIN},
        json={"username": username, "password": PASSWORD},
    )
    assert login.status_code == 200, login.text
    return created.json()["user"]


def _client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=s.app), base_url=BASE_URL)


def test_scenario_1_new_user_registers_and_logs_in():
    async def scenario():
        async with _client() as client:
            user = await _register(client, "novel-owner")
            assert user["username"].startswith("novel-owner")
            session = (await client.get("/api/auth/session")).json()
            assert session["guest"] is False
            assert session["read_only"] is False
            assert "import_document" in session["permissions"]

    asyncio.run(scenario())


def test_scenario_2_upload_long_novel_into_new_notebook():
    async def scenario():
        content = _novel()
        assert len(content) > 200 * 1024, "测试文本要足够长，才能覆盖大量分块"
        async with _client() as client:
            await _register(client, "novel-owner")
            created = await client.post(
                "/api/notebooks", headers={"origin": ORIGIN}, json={"name": "银河争霸战"}
            )
            assert created.status_code == 201, created.text
            notebook_id = created.json()["id"]
            uploaded = await client.post(
                "/api/notebooks/%s/files?upload_id=%s" % (notebook_id, os.urandom(6).hex()),
                headers={"origin": ORIGIN},
                files={"files": ("银河争霸战.md", content, "text/markdown")},
            )
            assert uploaded.status_code == 201, uploaded.text
            imported = uploaded.json()["imported"]
            assert len(imported) == 1
            assert imported[0]["title"] == "银河争霸战"
            documents = await client.get("/api/notebooks/%s/documents" % notebook_id)
            assert documents.status_code == 200
            assert imported[0]["source_id"] in {
                item["source_id"] for item in documents.json()["documents"]
            }

    asyncio.run(scenario())


def test_scenario_3_owner_shares_notebook_with_guest():
    async def scenario():
        async with _client() as owner, _client() as guest:
            await _register(owner, "share-owner")
            created = await owner.post(
                "/api/notebooks", headers={"origin": ORIGIN}, json={"name": "银河争霸战"}
            )
            notebook_id = created.json()["id"]
            targets = await owner.get("/api/notebooks/%s/share-targets" % notebook_id)
            assert targets.status_code == 200, targets.text
            guests = [item for item in targets.json()["users"] if item.get("is_guest")]
            assert guests, "共享目标里必须能找到固定游客账号"
            guest_id = guests[0]["id"]
            assert guest_id == GUEST_USER_ID
            shared = await owner.put(
                "/api/notebooks/%s/members/%s" % (notebook_id, guest_id),
                headers={"origin": ORIGIN},
                json={"role": "viewer"},
            )
            assert shared.status_code == 200, shared.text
            listing = await guest.get("/api/notebooks")
            assert listing.status_code == 200
            assert notebook_id in {item["id"] for item in listing.json()["notebooks"]}
            assert (await guest.get("/api/notebooks/%s/documents" % notebook_id)).status_code == 200
            escalated = await guest.put(
                "/api/notebooks/%s/members/%s" % (notebook_id, guest_id),
                headers={"origin": ORIGIN},
                json={"role": "editor"},
            )
            assert escalated.status_code == 403

    asyncio.run(scenario())


def test_scenario_4_guest_sees_and_uses_at_least_ten_free_models():
    async def scenario():
        catalog = [
            {"id": "free-model-%02d" % index, "name": "Free Model %d" % index}
            for index in range(12)
        ]
        async with _client() as guest:
            with patch.object(
                s.runtime, "get_model_settings", return_value={"provider_id": "openrouter", "model_id": catalog[0]["id"]}
            ), patch.object(s.runtime, "list_models", return_value=catalog):
                response = await guest.get("/api/models/guest")
                assert response.status_code == 200, response.text
                payload = response.json()
                assert payload["provider_id"] == "openrouter"
                assert len(payload["models"]) >= 10
                chosen = payload["models"][0]["id"]

                calls = []

                async def fake_run(ctx, question, notebook_ids, **kwargs):
                    calls.append((question, notebook_ids, kwargs))
                    return "answer"

                with patch.object(s.runtime, "run", new=fake_run):
                    chat = await guest.post(
                        "/api/chat",
                        headers={"origin": ORIGIN},
                        json={
                            "message": "用免费模型检索银河争霸战",
                            "knowledge_base_ids": [s.DEMO_KB_ID],
                            "model_id": chosen,
                            "catalog_provider_id": "openrouter",
                        },
                    )
                assert chat.status_code == 200, chat.text
                assert calls and calls[0][2]["model_id"] == chosen
                assert calls[0][2]["expected_provider_id"] == "openrouter"

    asyncio.run(scenario())


def test_embedding_runs_in_bounded_batches():
    """分批嵌入：单批不超过 EMBED_BATCH_SIZE，避免长文档一次性打满内存。"""
    import rag_core

    class FakeModel:
        def __init__(self):
            self.batches = []

        def embed(self, texts, batch_size=None):
            self.batches.append(len(texts))
            return [[0.0, 0.0, 0.0, 0.0] for _ in texts]

    fake = FakeModel()
    original = rag_core._FASTEMBED
    rag_core._FASTEMBED = fake
    try:
        with patch.dict(os.environ, {"RAG_EMBED": "fastembed"}):
            vectors = rag_core.embed(["文本 %d" % index for index in range(100)])
    finally:
        rag_core._FASTEMBED = original
    assert len(vectors) == 100
    assert fake.batches == [32, 32, 32, 4]
    assert all(0 < size <= rag_core.EMBED_BATCH_SIZE for size in fake.batches)
