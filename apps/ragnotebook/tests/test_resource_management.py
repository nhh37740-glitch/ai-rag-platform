import asyncio
import os
import io
import zipfile
from pathlib import Path
from pypdf import PdfWriter
from unittest.mock import patch
import httpx
from core_specifications import ModelRequestError, RequestContext
import server as s

ORIGIN = "http://testserver"

def client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=s.app), base_url=ORIGIN)

async def register(c, prefix):
    account = {"username": prefix + os.urandom(4).hex(), "password": "test-password-123"}
    response = await c.post("/api/auth/register", headers={"Origin": ORIGIN}, json=account)
    assert response.status_code == 201, response.text
    assert (await c.post("/api/auth/login", headers={"Origin": ORIGIN}, json=account)).status_code == 200
    return response.json()["user"]["id"]


async def completed_upload(owner, upload_id):
    for _ in range(100):
        response = await owner.get(f"/api/uploads/{upload_id}")
        assert response.status_code == 200
        state = response.json()
        if state["state"] != "running":
            return state
        await asyncio.sleep(0.02)
    raise AssertionError("background upload did not finish")


def test_background_upload_returns_before_embedding_and_holds_files_and_admission():
    async def run():
        async with client() as owner, client() as other:
            await register(owner, "async-owner")
            await register(other, "async-other")
            book = (await owner.post("/api/notebooks", headers={"Origin": ORIGIN}, json={"name": "后台长导入"})).json()["id"]
            second = (await other.post("/api/notebooks", headers={"Origin": ORIGIN}, json={"name": "其它导入"})).json()["id"]
            started, release = __import__("threading").Event(), __import__("threading").Event()
            paths = []
            original = s.rag_service.ingest
            def paused(ctx, path, knowledge_base_id, source_id="", progress=None):
                paths.append(Path(path))
                assert paths[-1].is_file()
                started.set()
                assert release.wait(10)
                return original(ctx, path, knowledge_base_id, source_id, progress)
            upload_id = "async-" + book
            try:
                with patch.object(s.rag_service, "ingest", new=paused):
                    response = await owner.post(f"/api/notebooks/{book}/files?background=true&upload_id={upload_id}", headers={"Origin": ORIGIN}, files={"files": ("novel.txt", "后台导入保留临时文件。".encode())})
                    assert response.status_code == 202, response.text
                    assert await asyncio.to_thread(started.wait, 5)
                    assert (await owner.get(f"/api/uploads/{upload_id}")).json()["state"] == "running"
                    assert (await other.get(f"/api/uploads/{upload_id}")).status_code == 404
                    assert (await owner.delete(f"/api/notebooks/{book}", headers={"Origin": ORIGIN})).status_code == 409
                    busy = await other.post(f"/api/notebooks/{second}/files?background=true", headers={"Origin": ORIGIN}, files={"files": ("other.txt", b"other")})
                    assert busy.status_code == 409
                    release.set()
                    done = await completed_upload(owner, upload_id)
            finally:
                release.set()
            assert done["state"] == "done"
            assert done["result"]["imported"][0]["bytes"] == len("后台导入保留临时文件。".encode())
            assert done["result"]["imported"][0]["sha256"]
            assert paths and not paths[0].exists()
            assert not s.IMPORT_LOCK.locked()
            assert (await owner.delete(f"/api/notebooks/{book}", headers={"Origin": ORIGIN})).status_code == 200
            assert (await other.delete(f"/api/notebooks/{second}", headers={"Origin": ORIGIN})).status_code == 200
    asyncio.run(run())


def test_background_document_error_finishes_cleans_files_and_allows_retry():
    async def run():
        async with client() as owner:
            await register(owner, "async-error")
            book = (await owner.post("/api/notebooks", headers={"Origin": ORIGIN}, json={"name": "后台错误"})).json()["id"]
            upload_id = "async-error-" + book
            seen = []
            original = s.rag_service.ingest
            def recording(ctx, path, *args):
                seen.append(Path(path))
                return original(ctx, path, *args)
            with patch.object(s.rag_service, "ingest", new=recording):
                response = await owner.post(f"/api/notebooks/{book}/files?background=true&upload_id={upload_id}", headers={"Origin": ORIGIN}, files={"files": ("broken.docx", b"not a ZIP")})
                assert response.status_code == 202
                failure = await completed_upload(owner, upload_id)
            assert failure["state"] == "error" and "DOCX" in failure["message"]
            assert seen and not seen[0].exists()
            assert not s.IMPORT_LOCK.locked()
            assert (await owner.get(f"/api/notebooks/{book}/documents")).json()["documents"] == []
            retry = await owner.post(f"/api/notebooks/{book}/files?background=true", headers={"Origin": ORIGIN}, files={"files": ("valid.txt", "重新上传正常文本。".encode())})
            assert retry.status_code == 202
            assert (await completed_upload(owner, retry.json()["upload_id"]))["state"] == "done"
            assert (await owner.delete(f"/api/notebooks/{book}", headers={"Origin": ORIGIN})).status_code == 200
    asyncio.run(run())


def test_corrupt_documents_end_progress_allow_retry_and_deletion():
    malformed_xml = io.BytesIO()
    with zipfile.ZipFile(malformed_xml, "w") as archive:
        archive.writestr("word/document.xml", "<broken")
    missing_body = io.BytesIO()
    with zipfile.ZipFile(missing_body, "w") as archive:
        archive.writestr("other.xml", "<document/>")
    encrypted = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.encrypt("private-test-password")
    writer.write(encrypted)
    cases = [("broken.docx", b"not a ZIP"), ("xml.docx", malformed_xml.getvalue()),
             ("missing.docx", missing_body.getvalue()), ("broken.pdf", b"not a PDF"),
             ("encrypted.pdf", encrypted.getvalue())]
    async def run():
        async with client() as owner:
            await register(owner, "corrupt-owner")
            for filename, content in cases:
                book = (await owner.post("/api/notebooks", headers={"Origin": ORIGIN}, json={"name": filename})).json()["id"]
                upload_id = "corrupt-" + book
                response = await owner.post(f"/api/notebooks/{book}/files?upload_id={upload_id}", headers={"Origin": ORIGIN}, files={"files": (filename, content)})
                assert response.status_code == 422, response.text
                assert response.headers["content-type"].startswith("application/json")
                assert filename in response.json()["detail"]
                progress = (await owner.get(f"/api/uploads/{upload_id}")).json()
                assert progress["state"] == "error"
                assert (await owner.get(f"/api/notebooks/{book}/documents")).json()["documents"] == []
                retry = await owner.post(f"/api/notebooks/{book}/files", headers={"Origin": ORIGIN}, files={"files": ("valid.txt", "正常文档可以重试。".encode())})
                assert retry.status_code == 201, retry.text
                assert (await owner.delete(f"/api/notebooks/{book}", headers={"Origin": ORIGIN})).status_code == 200
    asyncio.run(run())


def test_unexpected_ingestion_error_ends_task_without_hiding_programming_error():
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=s.app, raise_app_exceptions=False), base_url=ORIGIN) as owner:
            await register(owner, "unexpected-import")
            book = (await owner.post("/api/notebooks", headers={"Origin": ORIGIN}, json={"name": "程序错误回归"})).json()["id"]
            upload_id = "unexpected-" + book
            with patch.object(s.rag_service, "ingest", side_effect=AssertionError("internal diagnostic")):
                response = await owner.post(f"/api/notebooks/{book}/files?upload_id={upload_id}", headers={"Origin": ORIGIN}, files={"files": ("valid.txt", b"valid content")})
            assert response.status_code == 500
            progress = (await owner.get(f"/api/uploads/{upload_id}")).json()
            assert progress["state"] == "error"
            assert "internal diagnostic" not in progress["message"]
            assert (await owner.delete(f"/api/notebooks/{book}", headers={"Origin": ORIGIN})).status_code == 200
    asyncio.run(run())


def test_notebook_and_source_delete_enforce_owner_editor_viewer_and_origin():
    async def run():
        async with client() as owner, client() as editor, client() as viewer, client() as guest:
            owner_id = await register(owner, "delete-owner")
            editor_id = await register(editor, "delete-editor")
            viewer_id = await register(viewer, "delete-viewer")
            book = (await owner.post("/api/notebooks", headers={"Origin": ORIGIN}, json={"name": "删除测试"})).json()["id"]
            for uid, role in [(editor_id, "editor"), (viewer_id, "viewer"), ("guest", "viewer")]:
                assert (await owner.put(f"/api/notebooks/{book}/members/{uid}", headers={"Origin": ORIGIN}, json={"role": role})).status_code == 200
            upload = await owner.post(f"/api/notebooks/{book}/files", headers={"Origin": ORIGIN}, files={"files": ("long.txt", ("银河舰队完成跃迁。" * 100).encode(), "text/plain")})
            assert upload.status_code == 201, upload.text
            imported = upload.json()["imported"][0]
            assert imported["bytes"] > 1000 and imported["characters"] > 500
            params = {"source_id": imported["source_id"]}
            for user in [viewer, guest]:
                assert (await user.delete(f"/api/notebooks/{book}/documents", params=params, headers={"Origin": ORIGIN})).status_code == 403
                assert (await user.delete(f"/api/notebooks/{book}", headers={"Origin": ORIGIN})).status_code == 403
            assert (await owner.delete(f"/api/notebooks/{book}/documents", params=params, headers={"Origin": "http://wrong-origin"})).status_code == 403
            assert (await editor.delete(f"/api/notebooks/{book}", headers={"Origin": ORIGIN})).status_code == 403
            assert (await editor.delete(f"/api/notebooks/{book}/documents", params={"source_id": "other/private"}, headers={"Origin": ORIGIN})).status_code == 404
            assert (await editor.delete(f"/api/notebooks/{book}/documents", params=params, headers={"Origin": ORIGIN})).status_code == 200
            assert (await owner.get(f"/api/notebooks/{book}/documents")).json()["documents"] == []
            ctx = RequestContext("deletion-fixture", "request", owner_id)
            conversation_id = "delete-conversation-" + os.urandom(4).hex()
            s.data_service.save_conversation(ctx, {"id": conversation_id, "user_id": owner_id, "notebook_id": [book], "messages": []})
            assert (await owner.delete(f"/api/notebooks/{book}", headers={"Origin": ORIGIN})).status_code == 200
            assert s.data_service.get_notebook(s.BOOT_CONTEXT, book) is None
            assert s.data_service.get_conversation(ctx, conversation_id, owner_id) is None
            assert (await guest.get(f"/api/notebooks/{book}/documents")).status_code == 403
            # CMRC is protected even from its seeded owner.
            with patch.object(s, "_authorize_notebook", return_value=(s.BOOT_CONTEXT, None)):
                assert (await owner.delete(f"/api/notebooks/{s.DEMO_KB_ID}", headers={"Origin": ORIGIN})).status_code == 403
    asyncio.run(run())


def test_model_failures_and_overall_timeout_return_json_and_release_notebook():
    async def run():
        async with client() as guest:
            async def unavailable(*args, **kwargs):
                raise ModelRequestError("model_unavailable", "所选模型暂不可用", 503)
            payload = {"message": "银河舰队在哪？", "knowledge_base_ids": [s.DEMO_KB_ID]}
            before = (await guest.get("/api/llm/config")).json()["quota"]["remaining"]
            with patch.object(s.runtime, "run", new=unavailable):
                response = await guest.post("/api/chat", headers={"Origin": ORIGIN}, json=payload)
            assert response.status_code == 503
            assert response.json()["detail"]["code"] == "model_unavailable"
            assert response.json()["trace_id"]
            assert response.json()["quota"]["remaining"] == before - 1
            assert not s.ACTIVE_QUERIES
            cancelled = []
            async def stalled(*args, **kwargs):
                try:
                    await asyncio.sleep(10)
                finally:
                    cancelled.append(True)
            with patch.object(s.runtime, "run", new=stalled), patch.object(s, "CHAT_TIMEOUT_SECONDS", 0.01):
                response = await guest.post("/api/chat", headers={"Origin": ORIGIN}, json=payload)
            assert response.status_code == 504
            assert response.json()["detail"]["code"] == "chat_timeout"
            assert response.json()["quota"]["remaining"] == before - 2
            assert cancelled and not s.ACTIVE_QUERIES
    # The earlier quota test deliberately consumes today's allowance. Exercise
    # this test on a separate clock date while preserving the real quota path.
    with patch.object(s.auth_service, "_quota_date", return_value=("2099-10-13", "2099-10-14T00:00:00+08:00")):
        asyncio.run(run())


def test_client_disconnect_cancels_pending_model_operation():
    async def run():
        cancelled = []
        class Disconnected:
            async def is_disconnected(self):
                return True
        async def pending():
            try:
                await asyncio.sleep(10)
            finally:
                cancelled.append(True)
        try:
            await s._run_with_disconnect(Disconnected(), pending())
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError("disconnected request should be cancelled")
        assert cancelled
    asyncio.run(run())


def test_upload_progress_can_be_polled_during_single_document_embedding():
    async def run():
        async with client() as owner:
            await register(owner, "progress-owner")
            book = (await owner.post("/api/notebooks", headers={"Origin": ORIGIN}, json={"name": "进度测试"})).json()["id"]
            started, release = __import__("threading").Event(), __import__("threading").Event()
            original = s.rag_service.ingest
            def paused(ctx, path, knowledge_base_id, source_id="", progress=None):
                progress({"stage": "建立向量索引", "done": 32, "total": 100, "unit": "块"})
                started.set()
                assert release.wait(5)
                return original(ctx, path, knowledge_base_id, source_id, progress)
            try:
                with patch.object(s.rag_service, "ingest", new=paused):
                    task = asyncio.create_task(owner.post(f"/api/notebooks/{book}/files?upload_id=progress-{book}", headers={"Origin": ORIGIN}, files={"files": ("novel.txt", ("舰队跃迁。" * 200).encode(), "text/plain")}))
                    assert await asyncio.to_thread(started.wait, 5)
                    status = await owner.get(f"/api/uploads/progress-{book}")
                    assert status.json()["done"] == 32 and status.json()["total"] == 100
                    assert status.json()["unit"] == "块"
                    assert (await owner.delete(f"/api/notebooks/{book}", headers={"Origin": ORIGIN})).status_code == 409
                    release.set()
                    assert (await task).status_code == 201
            finally:
                release.set()
            assert (await owner.delete(f"/api/notebooks/{book}", headers={"Origin": ORIGIN})).status_code == 200
    asyncio.run(run())
