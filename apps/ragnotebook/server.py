from __future__ import annotations

# Enforce binary module loading before importing any business facade.
import runtime_boundary
PUBLISHED_MODULES = runtime_boundary.enforce_binary_runtime()

import asyncio
import hashlib
import json
import os
import re
import secrets
import tempfile
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from agent_facade import AgentService, make_provider, resolve_model_config
from auth_facade import AuthService
from core_specifications import RequestContext
from data_facade import DataService
from rag_facade import RagService

runtime_boundary.assert_binary_runtime(PUBLISHED_MODULES)

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[1]
WEB_DIR = ROOT / "apps" / "web"
KB_DIR = ROOT / "data" / "kb"
DEMO_KB_ID = "cmrc2018-demo"
DEMO_KB_DIR = KB_DIR / DEMO_KB_ID
STATE_DIR = Path(os.environ.get("STATE_DIR", str(ROOT / "data")))
SKILL_DIR = ROOT / "skills"
SESSION_COOKIE = "ragnotebook_session"
SESSION_TTL_SECONDS = 43200
TRACE_ACCESS: dict[str, tuple[str, list[str]]] = {}
UPLOAD_PROGRESS: dict[str, dict] = {}
SUPPORTED_EXTENSIONS = frozenset({".md", ".txt", ".docx", ".pdf"})
MAX_UPLOAD_BYTES = 25 * 1024 * 1024


def _load_env(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


_load_env(ROOT / ".env")
env_file = os.environ.get("RAG_LLM_ENV_FILE", str(ROOT / ".env.openrouter"))
if env_file:
    _load_env(Path(env_file))

BOOT_CONTEXT = RequestContext("boot", "boot")
data_service = DataService(os.environ.get("RAG_DATABASE_PATH", str(STATE_DIR / "ragnotebook.sqlite")))
data_service.initialize(BOOT_CONTEXT)
auth_service = AuthService(data_service, session_ttl_seconds=SESSION_TTL_SECONDS, daily_limit=100)
auth_service.initialize(
    BOOT_CONTEXT,
    os.environ.get("RAG_BOOTSTRAP_ADMIN_USERNAME", ""),
    os.environ.get("RAG_BOOTSTRAP_ADMIN_PASSWORD", ""),
)
# The data facade supplies the VectorStore port to RagService. HTTP routes only
# use RagService operations; they never call the store directly.
rag_service = RagService(data_service.vector_store(BOOT_CONTEXT), embedding_state=data_service)
rag_service.ensure_embedding_model(BOOT_CONTEXT)
MODEL_CONFIG = resolve_model_config(BOOT_CONTEXT, dict(os.environ))
provider = make_provider(MODEL_CONFIG.api_key, MODEL_CONFIG.base_url, MODEL_CONFIG.model)
runtime = AgentService(data_service, rag_service, skill_dir=str(SKILL_DIR), provider=provider, environment=dict(os.environ))


def _ctx(req: Request | None = None, *, user_id: str = "guest", session_id: str = "") -> RequestContext:
    trace_id = uuid.uuid4().hex
    if req is not None:
        existing = getattr(req.state, "auth_context", None)
        principal = getattr(req.state, "auth_principal", None)
        if existing is not None:
            trace_id = existing.trace_id
        if principal is not None:
            user_id = principal.user_id
    return RequestContext(trace_id, trace_id, user_id, session_id)


def _guest(ctx: RequestContext):
    return auth_service.guest(ctx)


def _identity(req: Request, *, required: bool = False):
    ctx = _ctx(req)
    token = req.cookies.get(SESSION_COOKIE, "")
    if token:
        try:
            principal = auth_service.authenticate_session(ctx, token)
        except (PermissionError, ValueError):
            if required:
                raise HTTPException(401, "登录已失效") from None
            principal = _guest(ctx)
    else:
        principal = _guest(ctx)
    ctx = RequestContext(ctx.trace_id, ctx.request_id, principal.user_id)
    req.state.auth_context = ctx
    req.state.auth_principal = principal
    return ctx, principal


def _authorize(req: Request, permission: str, *, required: bool = False):
    ctx, principal = _identity(req, required=required)
    try:
        auth_service.authorize(ctx, principal, permission)
    except PermissionError:
        raise HTTPException(403, "当前身份无权执行此操作") from None
    return ctx, principal


def _all_notebooks(ctx: RequestContext, user_id: str) -> list[dict]:
    return [dict(item) for item in data_service.list_notebooks(ctx, user_id)]


def _available_ids(ctx: RequestContext, user_id: str) -> list[str]:
    return [item["id"] for item in _all_notebooks(ctx, user_id)]


def _allowed_notebooks(req: Request) -> list[str]:
    ctx, principal = _authorize(req, "read")
    return _available_ids(ctx, principal.user_id)


def _authorize_notebook(req: Request, notebook_id: str, permission: str = "read"):
    ctx, principal = _identity(req)
    if notebook_id not in _available_ids(ctx, principal.user_id):
        raise HTTPException(403, "当前身份无权访问该笔记本")
    try:
        auth_service.authorize_notebook(ctx, principal, notebook_id, permission)
    except PermissionError:
        raise HTTPException(403, "当前身份没有该笔记本的操作权限") from None
    return ctx, principal


def _notebook_permissions(req: Request, notebook_id: str) -> list[str]:
    ctx, principal = _identity(req)
    return auth_service.notebook_permissions(ctx, principal, notebook_id)


def _notebook_view(record: dict, req: Request) -> dict:
    permissions = _notebook_permissions(req, record["id"])
    return {
        **{key: record.get(key) for key in ("id", "name", "created_at")},
        "document_count": len(rag_service.list_documents(_ctx(req), [record["id"]])),
        "writable": "import_document" in permissions,
        "permissions": permissions,
        "is_owner": data_service.get_notebook(_ctx(req), record["id"]).get("owner_user_id") == getattr(getattr(req.state, "auth_principal", None), "user_id", None),
    }


def _origin_is_same(req: Request) -> bool:
    origin = req.headers.get("origin", "")
    if not origin:
        return True
    try:
        parsed = urlsplit(origin)
    except ValueError:
        return False
    return parsed.netloc.lower() == req.headers.get("host", "").lower() and parsed.scheme in {"https", "http"} and not (parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password)


def _require_same_origin(req: Request) -> None:
    if not _origin_is_same(req):
        raise HTTPException(403, "跨站请求被拒绝")


def _cookie_secure(req: Request) -> bool:
    return req.url.scheme == "https" or req.headers.get("x-forwarded-proto", "").split(",", 1)[0].strip() == "https"


def _reserve_query(ctx: RequestContext) -> dict:
    try:
        return auth_service.reserve_query(ctx)
    except PermissionError:
        quota = auth_service.quota_status(ctx)
        raise HTTPException(429, {"message": "全站今日问答额度已用完，北京时间零点恢复", "quota": quota}, headers={"Cache-Control": "no-store"}) from None


def _demo_manifest() -> tuple[dict, list[tuple[Path, dict]]]:
    manifest_path = DEMO_KB_DIR / "knowledge-base-manifest.json"
    if not manifest_path.is_file():
        return {}, []
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    docs_dir = (DEMO_KB_DIR / "knowledge-documents").resolve()
    docs = []
    for item in manifest.get("documents", []):
        name = item.get("file", "") if isinstance(item, dict) else ""
        if name and name == Path(name).name and name.endswith(".md"):
            path = (docs_dir / name).resolve()
            if docs_dir in path.parents and path.is_file():
                docs.append((path, item))
    return manifest, docs


def _ensure_demo_notebook() -> None:
    current = data_service.get_notebook(BOOT_CONTEXT, DEMO_KB_ID)
    guest = auth_service.guest(BOOT_CONTEXT)
    guest_ctx = _ctx(user_id=guest.user_id)
    guest_notebooks = data_service.list_notebooks(guest_ctx, guest.user_id)
    if current is not None and any(item.get("id") == DEMO_KB_ID for item in guest_notebooks):
        return
    admin_username = os.environ.get("RAG_BOOTSTRAP_ADMIN_USERNAME", "")
    admin_password = os.environ.get("RAG_BOOTSTRAP_ADMIN_PASSWORD", "")
    if not admin_username or not admin_password:
        raise RuntimeError("首次初始化或修复 CMRC guest 分享需要 RAG_BOOTSTRAP_ADMIN_USERNAME 和 RAG_BOOTSTRAP_ADMIN_PASSWORD")
    admin_principal, bootstrap_token = auth_service.login(BOOT_CONTEXT, admin_username, admin_password)
    try:
        if current is None:
            manifest, _ = _demo_manifest()
            data_service.create_notebook(BOOT_CONTEXT, {
                "id": DEMO_KB_ID, "owner_user_id": admin_principal.user_id,
                "name": manifest.get("name", "CMRC2018 中文演示资料"),
                "created_at": "2026-10-11T00:00:00Z",
            })
        members = auth_service.list_members(BOOT_CONTEXT, admin_principal, DEMO_KB_ID)
        if not any(item.get("user_id") == guest.user_id for item in members):
            auth_service.set_member(BOOT_CONTEXT, admin_principal, DEMO_KB_ID, guest.user_id, "viewer")
    finally:
        auth_service.logout(BOOT_CONTEXT, bootstrap_token)

def _ensure_demo_documents() -> int:
    manifest, docs = _demo_manifest()
    existing = {item.get("source_id") for item in rag_service.list_documents(BOOT_CONTEXT, [DEMO_KB_ID])}
    imported = 0
    for path, _ in docs:
        source = f"{DEMO_KB_ID}/{path.stem}"
        if source not in existing:
            markdown = rag_service.parse_document(BOOT_CONTEXT, str(path))
            rag_service.ingest_markdown(BOOT_CONTEXT, markdown, source)
            imported += 1
    return imported


_ensure_demo_notebook()
demo_kb_imported = _ensure_demo_documents()


@asynccontextmanager
async def lifespan(app):
    yield
    await runtime.aclose(BOOT_CONTEXT)
    data_service.close(BOOT_CONTEXT)


app = FastAPI(title="RAGnotebook", lifespan=lifespan)


@app.get("/")
def index():
    return FileResponse(str(WEB_DIR / "index.html"))


@app.get("/api/demo")
def demo():
    manifest, docs = _demo_manifest()
    questions = [q for _, item in docs for q in item.get("questions", []) if isinstance(q, str)]
    suggestions = []
    for suggestion in manifest.get("featured_questions", []):
        if isinstance(suggestion, dict) and suggestion.get("question"):
            suggestions.append({"question": suggestion["question"], "topic": suggestion.get("topic", "知识库"), "title": suggestion.get("title", "CMRC2018")})
    settings = runtime.get_model_settings(BOOT_CONTEXT)
    provider_id = settings.get("provider_id", "mock")
    model_id = settings.get("model_id", "")
    return JSONResponse({"id": DEMO_KB_ID, "name": manifest.get("name", DEMO_KB_ID), "source": manifest.get("source", ""), "license": manifest.get("license", ""), "documents": len(docs), "questions": questions, "question_count": len(questions), "suggested_questions": suggestions, "imported": demo_kb_imported, "provider": provider_id, "model": model_id, "quota": auth_service.quota_status(BOOT_CONTEXT), "embedding": os.environ.get("RAG_EMBED", "fastembed").strip().lower()})


@app.get("/api/auth/session")
def auth_session(req: Request):
    ctx, principal = _identity(req)
    allowed = _available_ids(ctx, principal.user_id)
    return JSONResponse({"role": principal.role, "user_id": principal.user_id, "administrator": principal.role == "admin", "read_only": principal.role == "guest", "permissions": ["read", "query"] if principal.role == "guest" else ["read", "query", "create_notebook", "import_document", "write"], "allowed_notebook_ids": allowed, "guest": principal.role == "guest"}, headers={"Cache-Control": "no-store"})


@app.post("/api/auth/register")
async def register(req: Request):
    _require_same_origin(req)
    body = await req.json()
    try:
        user = auth_service.register(_ctx(req), body.get("username"), body.get("password"))
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, str(exc)) from None
    return JSONResponse({"user": user}, status_code=201, headers={"Cache-Control": "no-store"})


@app.post("/api/auth/login")
async def login(req: Request):
    _require_same_origin(req)
    body = await req.json()
    try:
        principal, token = auth_service.login(_ctx(req), body.get("username"), body.get("password"))
    except (ValueError, TypeError, PermissionError):
        raise HTTPException(401, "用户名或密码错误") from None
    response = JSONResponse({"user": {"user_id": principal.user_id, "role": principal.role}}, headers={"Cache-Control": "no-store"})
    response.set_cookie(SESSION_COOKIE, token, httponly=True, secure=_cookie_secure(req), samesite="lax", max_age=SESSION_TTL_SECONDS, path="/")
    return response


@app.post("/api/auth/logout")
def logout(req: Request):
    _require_same_origin(req)
    token = req.cookies.get(SESSION_COOKIE, "")
    if token:
        auth_service.logout(_ctx(req), token)
    response = JSONResponse({"logged_out": True}, headers={"Cache-Control": "no-store"})
    response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, secure=_cookie_secure(req), samesite="lax")
    return response



def _admin_context(req: Request):
    ctx, principal = _authorize(req, "authenticated", required=True)
    if principal.role != "admin":
        raise HTTPException(403, "仅全局管理员可管理模型")
    return ctx, principal

@app.get("/api/admin/users")
def admin_users(req: Request):
    ctx, principal = _authorize(req, "authenticated", required=True)
    try:
        return JSONResponse({"users": auth_service.list_admin_users(ctx, principal)}, headers={"Cache-Control": "no-store"})
    except PermissionError:
        raise HTTPException(403, "仅管理员可管理用户") from None


@app.patch("/api/admin/users/{user_id}")
async def set_user_active(user_id: str, req: Request):
    _require_same_origin(req)
    ctx, principal = _authorize(req, "authenticated", required=True)
    body = await req.json()
    if not isinstance(body, dict) or type(body.get("active")) is not bool:
        raise HTTPException(422, "active 必须为布尔值")
    try:
        auth_service.set_user_active(ctx, principal, user_id, body["active"])
    except (PermissionError, ValueError):
        raise HTTPException(403, "无法修改此用户状态") from None
    return JSONResponse({"updated": True}, headers={"Cache-Control": "no-store"})


@app.get("/api/notebooks")
def list_notebooks(req: Request):
    ctx, principal = _authorize(req, "read")
    permitted_ids = set(_available_ids(ctx, principal.user_id))
    records = [row for row in data_service.list_notebooks(ctx, principal.user_id) if row["id"] in permitted_ids]
    return JSONResponse({"notebooks": [_notebook_view(row, req) for row in records], "default_ids": [DEMO_KB_ID], "supported_extensions": sorted(SUPPORTED_EXTENSIONS), "max_upload_mb": MAX_UPLOAD_BYTES // (1024 * 1024)}, headers={"Cache-Control": "no-store"})


@app.get("/api/notebooks/{notebook_id}/suggestions")
def notebook_suggestions(notebook_id: str, req: Request):
    ctx, _ = _authorize_notebook(req, notebook_id)
    if notebook_id == DEMO_KB_ID:
        manifest, documents = _demo_manifest()
        by_file = {item.get("file"): item for _, item in documents}
        questions = []
        for item in manifest.get("featured_questions", []):
            doc = by_file.get(item.get("document")) if isinstance(item, dict) else None
            if doc and item.get("question") in doc.get("questions", []):
                questions.append({"question": item["question"], "topic": item.get("topic", "知识库"), "title": doc.get("title", "")})
        return JSONResponse({"notebook_id": notebook_id, "source": "curated", "questions": questions})
    docs = rag_service.list_documents(ctx, [notebook_id])
    return JSONResponse({"notebook_id": notebook_id, "source": "documents", "questions": [{"question": f"《{_doc_title(item['source_id'])}》主要讲了什么？", "topic": "全文", "title": _doc_title(item["source_id"])} for item in docs]})


@app.post("/api/notebooks")
async def create_notebook(req: Request):
    _require_same_origin(req)
    ctx, principal = _authorize(req, "create_notebook", required=True)
    body = await req.json()
    name = body.get("name", "")
    if not isinstance(name, str):
        raise HTTPException(422, "名称必须为文本")
    notebook_id = "notebook-" + uuid.uuid4().hex[:16]
    record = {"id": notebook_id, "owner_user_id": principal.user_id, "name": name.strip(), "created_at": datetime.now(timezone.utc).isoformat()}
    try:
        data_service.create_notebook(ctx, record)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    return JSONResponse(_notebook_view(record, req), status_code=201)


@app.get("/api/notebooks/{notebook_id}/share-targets")
def share_targets(notebook_id: str, req: Request):
    ctx, principal = _authorize_notebook(req, notebook_id, "manage_members")
    try:
        return JSONResponse({"users": auth_service.list_share_targets(ctx, principal, notebook_id)}, headers={"Cache-Control": "no-store"})
    except PermissionError:
        raise HTTPException(403, "没有成员管理权限") from None


@app.get("/api/notebooks/{notebook_id}/members")
def list_members(notebook_id: str, req: Request):
    ctx, principal = _authorize_notebook(req, notebook_id, "manage_members")
    return JSONResponse({"members": auth_service.list_members(ctx, principal, notebook_id)}, headers={"Cache-Control": "no-store"})


@app.put("/api/notebooks/{notebook_id}/members/{user_id}")
async def put_member(notebook_id: str, user_id: str, req: Request):
    _require_same_origin(req)
    ctx, principal = _authorize_notebook(req, notebook_id, "manage_members")
    body = await req.json()
    role = body.get("role") if isinstance(body, dict) else None
    try:
        auth_service.set_member(ctx, principal, notebook_id, user_id, role)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    except PermissionError:
        raise HTTPException(403, "没有成员管理权限") from None
    return JSONResponse({"updated": True}, headers={"Cache-Control": "no-store"})


@app.delete("/api/notebooks/{notebook_id}/members/{user_id}")
def delete_member(notebook_id: str, user_id: str, req: Request):
    _require_same_origin(req)
    ctx, principal = _authorize_notebook(req, notebook_id, "manage_members")
    try:
        auth_service.remove_member(ctx, principal, notebook_id, user_id)
    except (PermissionError, ValueError):
        raise HTTPException(403, "没有成员管理权限") from None
    return JSONResponse({"removed": True}, headers={"Cache-Control": "no-store"})


def _doc_title(source_id: str) -> str:
    return source_id.rsplit("/", 1)[-1]


@app.get("/api/notebooks/{notebook_id}/documents")
def notebook_documents(notebook_id: str, req: Request):
    ctx, _ = _authorize_notebook(req, notebook_id)
    documents = rag_service.list_documents(ctx, [notebook_id])
    return JSONResponse({"notebook_id": notebook_id, "name": data_service.get_notebook(ctx, notebook_id).get("name", notebook_id), "writable": "import_document" in _notebook_permissions(req, notebook_id), "permissions": _notebook_permissions(req, notebook_id), "documents": [{"title": _doc_title(item["source_id"]), "source_id": item["source_id"], "chunks": item.get("chunk_count", 0)} for item in documents]}, headers={"Cache-Control": "no-store"})


@app.post("/api/notebooks/{notebook_id}/files")
async def upload_documents(notebook_id: str, req: Request, files: list[UploadFile] = File(...), upload_id: str = ""):
    _require_same_origin(req)
    ctx, principal = _authorize(req, "authenticated", required=True)
    _authorize_notebook(req, notebook_id, "import_document")
    if not files:
        raise HTTPException(400, "至少选择一个文件")
    if upload_id and not re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", upload_id):
        raise HTTPException(422, "无效的上传任务标识")
    if upload_id in UPLOAD_PROGRESS:
        raise HTTPException(409, "上传任务标识已使用")
    progress = {"user_id": principal.user_id, "notebook_id": notebook_id, "state": "running", "stage": "暂存文件", "done": 0, "total": len(files), "message": ""}
    if upload_id:
        UPLOAD_PROGRESS[upload_id] = progress

    staged = []
    try:
        with tempfile.TemporaryDirectory(prefix="ragnotebook-upload-") as temporary_dir:
            temporary_root = Path(temporary_dir)
            for index, upload in enumerate(files):
                original_name = (upload.filename or "document").replace("\\", "/").rsplit("/", 1)[-1].strip()
                if not original_name or original_name in {".", ".."}:
                    original_name = "document"
                extension = Path(original_name).suffix.lower()
                if extension not in SUPPORTED_EXTENSIONS:
                    supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
                    raise HTTPException(415, f"{original_name}: 仅支持 {supported}")
                try:
                    content = await upload.read(MAX_UPLOAD_BYTES + 1)
                finally:
                    await upload.close()
                if len(content) > MAX_UPLOAD_BYTES:
                    raise HTTPException(413, f"{original_name}: 文件不能超过 25 MB")
                temporary_source = temporary_root / f"source-{index}{extension}"
                temporary_source.write_bytes(content)
                staged.append((original_name, temporary_source))

            imported = []
            progress.update(stage="解析并入库", total=len(staged), done=0)
            for index, (filename, temporary_source) in enumerate(staged, start=1):
                safe_stem = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", Path(filename).stem).strip("-_")[:60] or "document"
                source_id = f"{notebook_id}/{safe_stem}-{uuid.uuid4().hex[:8]}"
                try:
                    result = await asyncio.to_thread(rag_service.ingest, ctx, str(temporary_source), notebook_id, source_id)
                except ValueError as exc:
                    raise HTTPException(422, f"{filename}: {exc}") from None
                imported.append({"title": Path(filename).stem, "source_id": result.source_id, "chunks": result.chunk_count, "original_name": filename})
                progress.update(done=index, message=f"已导入 {index}/{len(staged)} 篇来源")

        progress.update(state="done", stage="完成", done=len(staged), total=len(staged), message=f"已导入 {len(imported)} 篇来源")
        return JSONResponse({"notebook_id": notebook_id, "imported": imported}, status_code=201)
    except HTTPException as exc:
        progress.update(state="error", stage="失败", message=str(exc.detail))
        raise
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        progress.update(state="error", stage="失败", message=str(exc))
        raise HTTPException(422, "文件解析或入库失败") from None
    finally:
        for upload in files:
            await upload.close()


@app.get("/api/uploads/{upload_id}")
def upload_status(upload_id: str, req: Request):
    _, principal = _authorize(req, "authenticated", required=True)
    record = UPLOAD_PROGRESS.get(upload_id)
    if record is None or (record["user_id"] != principal.user_id and principal.role != "admin"):
        raise HTTPException(404, "没有这个上传任务")
    _authorize_notebook(req, record["notebook_id"], "import_document")
    return JSONResponse({"upload_id": upload_id, **{key: value for key, value in record.items() if key != "user_id"}})


def _conversation_scope(conversation: dict) -> list[str]:
    value = conversation.get("notebook_id", [])
    if isinstance(value, list):
        return value if all(isinstance(item, str) for item in value) else []
    try:
        value = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return []
    return value if isinstance(value, list) and all(isinstance(item, str) for item in value) else []


@app.get("/api/conversations")
def list_conversations(req: Request):
    ctx, principal = _authorize(req, "authenticated", required=True)
    allowed = set(_available_ids(ctx, principal.user_id))
    rows = data_service.list_conversations(ctx, principal.user_id, None)
    visible = []
    for conversation in rows:
        scope = _conversation_scope(conversation)
        if scope and set(scope) <= allowed:
            visible.append(conversation)
    return JSONResponse({"conversations": visible}, headers={"Cache-Control": "no-store"})


@app.post("/api/conversations")
async def create_conversation(req: Request):
    _require_same_origin(req)
    ctx, principal = _authorize(req, "authenticated", required=True)
    body = await req.json()
    notebook_ids = body.get("knowledge_base_ids", [DEMO_KB_ID])
    selected = _selected_notebook_ids(notebook_ids, req)
    conversation_id = uuid.uuid4().hex
    record = {"id": conversation_id, "user_id": principal.user_id, "notebook_id": json.dumps(sorted(selected), ensure_ascii=False), "title": str(body.get("title", "新会话"))[:120], "messages": []}
    data_service.save_conversation(ctx, record)
    return JSONResponse({"conversation": record}, status_code=201, headers={"Cache-Control": "no-store"})


def _selected_notebook_ids(raw, req: Request) -> list[str]:
    if raw is None:
        raw = [DEMO_KB_ID]
    if isinstance(raw, str):
        raw = raw.split(",")
    if not isinstance(raw, list) or any(not isinstance(value, str) for value in raw):
        raise HTTPException(422, "knowledge_base_ids 必须是字符串数组")
    selected = list(dict.fromkeys(value.strip() for value in raw if value.strip()))
    permitted = set(_allowed_notebooks(req))
    if set(selected) - permitted:
        raise HTTPException(403, "当前身份无权访问该笔记本")
    for notebook_id in selected:
        _authorize_notebook(req, notebook_id, "query")
    return selected


@app.get("/api/conversations/{conversation_id}")
def get_conversation(conversation_id: str, req: Request):
    ctx, principal = _authorize(req, "authenticated", required=True)
    result = data_service.get_conversation(ctx, conversation_id, principal.user_id)
    if result is None:
        raise HTTPException(404, "会话不存在")
    scope = _conversation_scope(result)
    if not scope or not set(scope) <= set(_available_ids(ctx, principal.user_id)):
        raise HTTPException(404, "会话不存在")
    return JSONResponse({"conversation": result}, headers={"Cache-Control": "no-store"})


@app.delete("/api/conversations/{conversation_id}")
def delete_conversation(conversation_id: str, req: Request):
    _require_same_origin(req)
    ctx, principal = _authorize(req, "authenticated", required=True)
    existing = data_service.get_conversation(ctx, conversation_id, principal.user_id)
    if existing is None:
        raise HTTPException(404, "会话不存在")
    scope = _conversation_scope(existing)
    if not scope or not set(scope) <= set(_available_ids(ctx, principal.user_id)):
        raise HTTPException(404, "会话不存在")
    data_service.delete_conversation(ctx, conversation_id, principal.user_id)
    return JSONResponse({"deleted": True}, headers={"Cache-Control": "no-store"})


def _web_key_allowed(req: Request) -> bool:
    origin = req.headers.get("origin", "")
    try:
        parsed = urlsplit(origin)
        host = parsed.hostname or ""
    except ValueError:
        return False
    if parsed.netloc.lower() != req.headers.get("host", "").lower() or parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password:
        return False
    return parsed.scheme == "https" or (parsed.scheme == "http" and host in {"localhost", "127.0.0.1", "::1"})


@app.post("/api/chat")
async def chat(req: Request):
    _require_same_origin(req)
    ctx, principal = _identity(req)
    body = await req.json()
    if not isinstance(body, dict):
        raise HTTPException(422, "请求体必须为对象")
    if "provider_id" in body:
        raise HTTPException(422, "Provider 只能由管理员在模型设置中切换")
    message = body.get("message", "")
    if not isinstance(message, str) or not message.strip():
        raise HTTPException(422, "message 必须为非空文本")
    selected = _selected_notebook_ids(body.get("knowledge_base_ids"), req)
    conversation_id = body.get("conversation_id")
    persistent = principal.role != "guest"
    if persistent and not conversation_id:
        conversation_id = uuid.uuid4().hex
        data_service.save_conversation(ctx, {"id": conversation_id, "user_id": principal.user_id, "notebook_id": json.dumps(sorted(selected)), "title": message[:120], "messages": []})
    conversation = None
    if persistent and conversation_id:
        conversation = data_service.get_conversation(ctx, conversation_id, principal.user_id)
        if conversation is None:
            raise HTTPException(404, "会话不存在")
        existing_scope = _conversation_scope(conversation)
        if existing_scope != sorted(selected):
            raise HTTPException(409, "会话笔记本范围已变化，请新建会话")
    ctx = RequestContext(ctx.trace_id, ctx.request_id, principal.user_id,
                         conversation_id if persistent else uuid.uuid4().hex)
    model_id = body.get("model_id")
    catalog_provider_id = body.get("catalog_provider_id")
    if principal.role == "guest":
        has_model_choice = "model_id" in body or "catalog_provider_id" in body
        if has_model_choice and (
            not isinstance(model_id, str) or not model_id.strip() or len(model_id) > 256
            or not isinstance(catalog_provider_id, str) or not catalog_provider_id.strip()
        ):
            raise HTTPException(422, "游客模型选择无效，请重新选择当前 Provider 下的模型")
        if has_model_choice:
            settings = runtime.get_model_settings(ctx)
            if catalog_provider_id != settings["provider_id"]:
                raise HTTPException(409, "当前 Provider 已切换，请重新选择模型")
            try:
                available = runtime.list_models(ctx, settings["provider_id"], dict(os.environ))
            except ValueError:
                raise HTTPException(503, "当前 Provider 的模型目录暂不可用") from None
            if model_id not in {item["id"] for item in available}:
                raise HTTPException(422, "该模型不在当前 Provider 的可选目录中")
    elif "model_id" in body or "catalog_provider_id" in body:
        raise HTTPException(422, "只有游客可以指定本次问答模型")
    _reserve_query(ctx)
    trace_id = ctx.trace_id
    TRACE_ACCESS[trace_id] = (principal.user_id, selected)
    if len(TRACE_ACCESS) > 2048:
        TRACE_ACCESS.pop(next(iter(TRACE_ACCESS)))
    try:
        answer = await runtime.run(
            ctx, message, selected, allow_write_tools=principal.role == "admin",
            model_id=model_id if principal.role == "guest" else None,
            expected_provider_id=catalog_provider_id if principal.role == "guest" else None,
            history=conversation.get("messages", []) if persistent else None,
            memory_enabled=persistent,
        )
    except ValueError as exc:
        if "Provider" in str(exc) or "模型" in str(exc):
            raise HTTPException(409, "当前模型目录已变化，请重新选择模型后重试") from None
        raise
    if persistent:
        msgs = list((conversation or {}).get("messages", []))
        msgs.extend([{"role": "user", "content": message}, {"role": "assistant", "content": answer, "trace_id": trace_id}])
        data_service.save_conversation(ctx, {"id": conversation_id, "user_id": principal.user_id, "notebook_id": json.dumps(sorted(selected)), "title": (conversation or {}).get("title") or message[:120], "messages": msgs})
    return JSONResponse({"answer": answer, "trace_id": trace_id, "knowledge_base_ids": selected, "conversation_id": conversation_id, "quota": auth_service.quota_status(ctx)}, headers={"Cache-Control": "no-store"})


@app.get("/api/llm/config")
def llm_config(req: Request):
    ctx, principal = _identity(req)
    settings = runtime.get_model_settings(ctx)
    provider_id = settings.get("provider_id", "mock")
    providers = runtime.list_model_providers(ctx, dict(os.environ))
    selected = next((item for item in providers if item.get("id", item.get("provider_id")) == provider_id), {})
    return JSONResponse({"server_key_configured": bool(selected.get("configured", False)), "provider": provider_id, "model": settings.get("model_id", ""), "free_models_only": provider_id == "openrouter", "quota": auth_service.quota_status(ctx)}, headers={"Cache-Control": "no-store"})


@app.get("/api/models/guest")
def guest_models(req: Request):
    ctx, principal = _identity(req)
    if principal.role != "guest":
        raise HTTPException(403, "此接口仅供游客选择本次问答模型")
    settings = runtime.get_model_settings(ctx)
    try:
        models = runtime.list_models(ctx, settings["provider_id"], dict(os.environ))
    except ValueError:
        raise HTTPException(503, "当前 Provider 的模型目录暂不可用") from None
    return JSONResponse({"provider_id": settings["provider_id"],
                         "default_model_id": settings["model_id"], "models": models},
                        headers={"Cache-Control": "no-store"})


@app.get("/api/models/providers")
def model_providers(req: Request):
    ctx, principal = _admin_context(req)
    return JSONResponse({"providers": runtime.list_model_providers(ctx, dict(os.environ))}, headers={"Cache-Control": "no-store"})


@app.get("/api/models/settings")
def get_model_settings(req: Request):
    ctx, _ = _admin_context(req)
    return JSONResponse(runtime.get_model_settings(ctx), headers={"Cache-Control": "no-store"})


@app.get("/api/models/{provider_id}")
def list_models(provider_id: str, req: Request):
    ctx, _ = _admin_context(req)
    return JSONResponse({"models": runtime.list_models(ctx, provider_id, dict(os.environ))}, headers={"Cache-Control": "no-store"})


@app.put("/api/models/settings")
async def update_model_settings(req: Request):
    _require_same_origin(req)
    ctx, _ = _admin_context(req)
    body = await req.json()
    if not isinstance(body, dict) or set(body) != {"provider_id", "model_id"}:
        raise HTTPException(422, "仅允许 provider_id 和 model_id")
    result = await asyncio.to_thread(runtime.update_model_settings, ctx, body["provider_id"], body["model_id"])
    return JSONResponse(result, headers={"Cache-Control": "no-store"})


@app.get("/api/trace/{trace_id}")
def trace(trace_id: str, req: Request):
    _, principal = _identity(req)
    access = TRACE_ACCESS.get(trace_id)
    # The random trace_id in the chat response is the guest's short-lived capability.
    if access is None or (principal.role == "guest" and access[0] != "guest") or (
        principal.role != "guest" and principal.role != "admin" and access[0] != principal.user_id
    ):
        raise HTTPException(404, "没有这个问答记录")
    for notebook_id in access[1]:
        _authorize_notebook(req, notebook_id, "query")
    return JSONResponse([event.__dict__ for event in rag_service.get(trace_id)], headers={"Cache-Control": "no-store"})


app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")
