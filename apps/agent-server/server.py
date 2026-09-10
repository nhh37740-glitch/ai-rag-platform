from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import re
import uuid
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from agent_runtime import AgentRuntime
from core_contracts import RequestContext
from document_upload import (
    MAX_UPLOAD_BYTES,
    SUPPORTED_EXTENSIONS,
    UploadValidationError,
    convert_uploaded_documents,
)
from ingestion import chunk as chunk_text, parse as parse_doc
from llm_gateway import DeepSeekProvider, MockProvider
from memory import make_memory
from observability import make_trace_store
from rag_core import InMemoryVectorStore, embed
from skill_runtime import SkillRegistry
from tool_runtime import default_registry, tool

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[1]
KB_DIR = ROOT / "data" / "kb"
USER_NOTEBOOKS_DIR = KB_DIR / "user-notebooks"
SKILL_DIR = ROOT / "skills"


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip())


_load_dotenv(ROOT / ".env")

DEMO_KB_ID = os.environ.get("DEMO_KB_ID", "cmrc2018-demo")
DEMO_KB_DIR = KB_DIR / DEMO_KB_ID
DB_PATH = os.environ.get("DB_PATH", str(ROOT / "data" / "app.db"))
API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
INDEX_PATH = os.environ.get("INDEX_PATH", str(ROOT / "data" / "index.json"))

trace_store = make_trace_store()
memory = make_memory(DB_PATH)
vector_store = InMemoryVectorStore()
skills = SkillRegistry()
skills.load_dir(str(SKILL_DIR))

provider = DeepSeekProvider(API_KEY, BASE_URL, MODEL) if API_KEY else MockProvider("qa")
tools = default_registry()


@tool("create_issue", "create a bug/issue", {"type": "object", "properties": {"title": {"type": "string"}, "priority": {"type": "string"}}, "required": ["title"]})
def _create_issue(title: str, priority: str = "P2") -> str:
    return f"已创建 Issue：{title}（优先级 {priority}，编号 #1{abs(hash(title)) % 9000 + 1000}）"


@tool("get_commits", "查询最近提交", {"type": "object", "properties": {"repo": {"type": "string"}, "since": {"type": "string"}}, "required": ["repo"]})
def _get_commits(repo: str = "demo", since: str = "1d") -> str:
    return "最近提交: 3, 修复网关 keep-alive 超时; 2, 优化索引查询; 1, 更新 API 文档"


@tool("search_employee", "查询项目成员", {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]})
def _search_employee(query: str) -> str:
    if "后端" in query:
        return "后端组: 张三(网关)、李四(存储)、王五(Agent)"
    return "未找到匹配成员"


def _load_demo_knowledge_base() -> tuple[dict, list[tuple[Path, dict]]]:
    """Load the bundled public corpus from the project knowledge base."""
    knowledge_base_dir = DEMO_KB_DIR
    manifest_path = knowledge_base_dir / "knowledge-base-manifest.json"
    if not manifest_path.is_file():
        return {}, []
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    documents_dir = (knowledge_base_dir / "knowledge-documents").resolve()
    documents: list[tuple[Path, dict]] = []
    for item in manifest.get("documents", []):
        filename = item.get("file", "") if isinstance(item, dict) else ""
        if not filename or filename != Path(filename).name or not filename.endswith(".md"):
            continue
        path = (documents_dir / filename).resolve()
        if documents_dir in path.parents and path.is_file():
            documents.append((path, item))
    return manifest, documents


def _user_notebook_path(notebook_id: str) -> Path:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{7,63}", notebook_id):
        raise ValueError("无效的笔记本标识")
    path = (USER_NOTEBOOKS_DIR / notebook_id).resolve()
    if USER_NOTEBOOKS_DIR.resolve() not in path.parents:
        raise ValueError("无效的笔记本路径")
    return path


def _read_user_notebook(notebook_dir: Path) -> dict:
    metadata_path = notebook_dir / "notebook-metadata.json"
    if not metadata_path.is_file():
        return {}
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return metadata if metadata.get("id") == notebook_dir.name else {}


def _write_user_notebook(notebook_dir: Path, metadata: dict) -> None:
    metadata_path = notebook_dir / "notebook-metadata.json"
    temporary_path = notebook_dir / ".notebook-metadata.tmp"
    temporary_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary_path.replace(metadata_path)


def _list_user_notebooks() -> list[tuple[Path, dict]]:
    if not USER_NOTEBOOKS_DIR.is_dir():
        return []
    notebooks = []
    for notebook_dir in sorted(path for path in USER_NOTEBOOKS_DIR.iterdir() if path.is_dir()):
        metadata = _read_user_notebook(notebook_dir)
        if metadata:
            notebooks.append((notebook_dir, metadata))
    return notebooks


def _public_notebook(metadata: dict, writable: bool) -> dict:
    return {
        "id": metadata["id"],
        "name": metadata.get("name", metadata["id"]),
        "description": metadata.get("description", ""),
        "document_count": len(metadata.get("documents", [])),
        "writable": writable,
    }


def _available_notebook_ids() -> set[str]:
    return {DEMO_KB_ID, *[metadata["id"] for _, metadata in _list_user_notebooks()]}


def _selected_notebook_ids(raw_ids) -> list[str]:
    if raw_ids is None:
        return [DEMO_KB_ID]
    if isinstance(raw_ids, str):
        raw_ids = raw_ids.split(",")
    if not isinstance(raw_ids, list):
        raise HTTPException(status_code=400, detail="knowledge_base_ids 必须是字符串数组")
    selected = list(dict.fromkeys(item.strip() for item in raw_ids if isinstance(item, str) and item.strip()))
    unknown = set(selected) - _available_notebook_ids()
    if unknown:
        raise HTTPException(status_code=400, detail=f"未知知识库: {', '.join(sorted(unknown))}")
    return selected


def _load_kb() -> tuple[InMemoryVectorStore, int]:
    store = InMemoryVectorStore()
    loaded_sources: set[str] = set()
    index = Path(INDEX_PATH)
    if index.exists():
        data = json.loads(index.read_text(encoding="utf-8"))
        if data.get("embed", "__unknown__") == os.environ.get("RAG_EMBED", "hash"):
            for s in data.get("sources", []):
                store.add(s["id"], s["chunks"], s["embs"])
                loaded_sources.add(s["id"])
    files = sorted(f for f in KB_DIR.glob("*.md") if f.name.lower() != "readme.md")
    for f in files:
        source_id = f"local-documents/{f.stem}"
        if source_id in loaded_sources:
            continue
        chunks = chunk_text(parse_doc(str(f)))
        store.add(source_id, chunks, embed(chunks))
        loaded_sources.add(source_id)

    _, demo_documents = _load_demo_knowledge_base()
    imported = 0
    for path, _ in demo_documents:
        source_id = f"{DEMO_KB_ID}/{path.stem}"
        if source_id in loaded_sources:
            imported += 1
            continue
        chunks = chunk_text(parse_doc(str(path)))
        store.add(source_id, chunks, embed(chunks))
        loaded_sources.add(source_id)
        imported += 1

    for notebook_dir, metadata in _list_user_notebooks():
        documents_dir = notebook_dir / "markdown-documents"
        for document in metadata.get("documents", []):
            markdown_file = document.get("markdown_file", "")
            path = documents_dir / Path(markdown_file).name
            if not markdown_file or not path.is_file():
                continue
            source_id = f"{metadata['id']}/{path.stem}"
            if source_id in loaded_sources:
                continue
            chunks = chunk_text(parse_doc(str(path)))
            store.add(source_id, chunks, embed(chunks))
            loaded_sources.add(source_id)
    return store, imported


vector_store, demo_kb_imported = _load_kb()

runtime = AgentRuntime(
    provider=provider,
    vector_store=vector_store,
    memory=memory,
    tools=tools,
    skills=skills,
    tracing=trace_store,
)

app = FastAPI(title="Dev Knowledge Agent")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(str(BASE / "webui" / "index.html"))


@app.get("/api/demo")
def demo() -> JSONResponse:
    manifest, documents = _load_demo_knowledge_base()
    questions = [
        question
        for _, item in documents
        for question in item.get("questions", [])
        if isinstance(question, str) and question.strip()
    ]
    document_items = {item.get("file"): item for _, item in documents}
    suggested_questions = []
    for suggestion in manifest.get("featured_questions", []):
        if not isinstance(suggestion, dict):
            continue
        document = document_items.get(suggestion.get("document"))
        question = suggestion.get("question", "")
        if not document or question not in document.get("questions", []):
            continue
        suggested_questions.append(
            {
                "question": question,
                "topic": suggestion.get("topic", "知识库"),
                "title": document.get("title", Path(document["file"]).stem),
            }
        )
    return JSONResponse(
        {
            "id": manifest.get("id", DEMO_KB_ID),
            "name": manifest.get("name", DEMO_KB_ID),
            "source": manifest.get("source", ""),
            "license": manifest.get("license", ""),
            "documents": len(documents),
            "questions": questions,
            "question_count": len(questions),
            "suggested_questions": suggested_questions,
            "imported": demo_kb_imported,
            "knowledge_base": "data/kb/cmrc2018-demo",
            "purpose": "project-demo-only",
        }
    )


@app.get("/api/notebooks")
def list_notebooks() -> JSONResponse:
    manifest, documents = _load_demo_knowledge_base()
    built_in = {
        "id": DEMO_KB_ID,
        "name": manifest.get("name", DEMO_KB_ID),
        "description": "项目内置的公开中文演示知识库",
        "document_count": len(documents),
        "writable": False,
    }
    user_notebooks = [_public_notebook(metadata, True) for _, metadata in _list_user_notebooks()]
    return JSONResponse(
        {
            "notebooks": [built_in, *user_notebooks],
            "default_ids": [DEMO_KB_ID],
            "supported_extensions": sorted(SUPPORTED_EXTENSIONS),
            "max_upload_mb": MAX_UPLOAD_BYTES // (1024 * 1024),
        }
    )


@app.post("/api/notebooks")
async def create_notebook(req: Request) -> JSONResponse:
    body = await req.json()
    name = str(body.get("name", "")).strip()
    description = str(body.get("description", "")).strip()
    if not name or len(name) > 80:
        raise HTTPException(status_code=400, detail="笔记本名称长度应为 1-80 个字符")
    if len(description) > 300:
        raise HTTPException(status_code=400, detail="笔记本说明不能超过 300 个字符")
    notebook_id = f"notebook-{uuid.uuid4().hex[:12]}"
    notebook_dir = _user_notebook_path(notebook_id)
    (notebook_dir / "markdown-documents").mkdir(parents=True)
    metadata = {
        "id": notebook_id,
        "name": name,
        "description": description,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "documents": [],
    }
    _write_user_notebook(notebook_dir, metadata)
    return JSONResponse(_public_notebook(metadata, True), status_code=201)


@app.post("/api/notebooks/{notebook_id}/files")
async def upload_notebook_files(notebook_id: str, files: list[UploadFile] = File(...)) -> JSONResponse:
    try:
        notebook_dir = _user_notebook_path(notebook_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    metadata = _read_user_notebook(notebook_dir)
    if not metadata:
        raise HTTPException(status_code=404, detail="笔记本不存在")
    try:
        converted = await convert_uploaded_documents(files)
    except UploadValidationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    documents_dir = notebook_dir / "markdown-documents"
    documents_dir.mkdir(exist_ok=True)
    imported = []
    for original_name, markdown in converted:
        safe_stem = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", Path(original_name).stem).strip("-_")[:60] or "document"
        markdown_file = f"{safe_stem}-{uuid.uuid4().hex[:8]}.md"
        markdown_path = documents_dir / markdown_file
        markdown_path.write_text(markdown, encoding="utf-8")
        chunks = chunk_text(parse_doc(str(markdown_path)))
        source_id = f"{notebook_id}/{markdown_path.stem}"
        vector_store.add(source_id, chunks, embed(chunks))
        document = {
            "original_name": original_name,
            "markdown_file": markdown_file,
            "title": Path(original_name).stem,
            "chunks": len(chunks),
        }
        metadata["documents"].append(document)
        imported.append(document)
    _write_user_notebook(notebook_dir, metadata)
    return JSONResponse({"notebook_id": notebook_id, "imported": imported}, status_code=201)


@app.post("/api/chat")
async def chat(req: Request) -> JSONResponse:
    body = await req.json()
    user_id = body.get("user_id", "anon")
    session_id = body.get("session_id", "s1")
    message = body.get("message", "")
    knowledge_base_ids = _selected_notebook_ids(body.get("knowledge_base_ids"))
    trace_id = uuid.uuid4().hex
    ctx = RequestContext(trace_id=trace_id, request_id=trace_id, user_id=user_id, session_id=session_id)
    answer = await runtime.run(ctx, message, knowledge_base_ids)
    return JSONResponse({"answer": answer, "trace_id": trace_id, "knowledge_base_ids": knowledge_base_ids})


@app.get("/api/chat/stream")
async def chat_stream(
    message: str,
    session_id: str = "s1",
    user_id: str = "u",
    knowledge_base_ids: str = DEMO_KB_ID,
):
    selected_ids = _selected_notebook_ids(knowledge_base_ids)

    async def gen():
        trace_id = uuid.uuid4().hex
        ctx = RequestContext(trace_id=trace_id, request_id=trace_id, user_id=user_id, session_id=session_id)
        answer = await runtime.run(ctx, message, selected_ids)
        yield f"data: {json.dumps({'answer': answer, 'trace_id': trace_id, 'knowledge_base_ids': selected_ids}, ensure_ascii=False)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.get("/api/trace/{trace_id}")
def trace(trace_id: str) -> JSONResponse:
    events = trace_store.get(trace_id)
    return JSONResponse([e.__dict__ for e in events])


app.mount("/static", StaticFiles(directory=str(BASE / "webui")), name="static")
