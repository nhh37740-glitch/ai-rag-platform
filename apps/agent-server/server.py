from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from agent_runtime import AgentRuntime
from core_contracts import RequestContext
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
DATASETS_DIR = ROOT / "data" / "datasets"
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

DEMO_DATASET_ID = os.environ.get("DEMO_DATASET_ID", "cmrc2018-demo")
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


def _load_demo_dataset() -> tuple[dict, list[tuple[Path, dict]]]:
    """Load the bundled public demo corpus without accepting arbitrary paths."""
    dataset_dir = DATASETS_DIR / DEMO_DATASET_ID
    manifest_path = dataset_dir / "manifest.json"
    if not manifest_path.is_file():
        return {}, []
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    documents_dir = (dataset_dir / "documents").resolve()
    documents: list[tuple[Path, dict]] = []
    for item in manifest.get("documents", []):
        filename = item.get("file", "") if isinstance(item, dict) else ""
        if not filename or filename != Path(filename).name or not filename.endswith(".md"):
            continue
        path = (documents_dir / filename).resolve()
        if documents_dir in path.parents and path.is_file():
            documents.append((path, item))
    return manifest, documents


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
    files = sorted(KB_DIR.glob("*.md"))
    for f in files:
        if f.stem in loaded_sources:
            continue
        chunks = chunk_text(parse_doc(str(f)))
        store.add(f.stem, chunks, embed(chunks))
        loaded_sources.add(f.stem)

    _, demo_documents = _load_demo_dataset()
    imported = 0
    for path, _ in demo_documents:
        if path.stem in loaded_sources:
            imported += 1
            continue
        chunks = chunk_text(parse_doc(str(path)))
        store.add(path.stem, chunks, embed(chunks))
        loaded_sources.add(path.stem)
        imported += 1
    return store, imported


vector_store, demo_imported = _load_kb()

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
    manifest, documents = _load_demo_dataset()
    questions = [
        question
        for _, item in documents
        for question in item.get("questions", [])
        if isinstance(question, str) and question.strip()
    ]
    return JSONResponse(
        {
            "id": manifest.get("id", DEMO_DATASET_ID),
            "name": manifest.get("name", DEMO_DATASET_ID),
            "source": manifest.get("source", ""),
            "license": manifest.get("license", ""),
            "documents": len(documents),
            "questions": questions,
            "question_count": len(questions),
            "imported": demo_imported,
            "purpose": "project-demo-only",
        }
    )


@app.post("/api/chat")
async def chat(req: Request) -> JSONResponse:
    body = await req.json()
    user_id = body.get("user_id", "anon")
    session_id = body.get("session_id", "s1")
    message = body.get("message", "")
    trace_id = uuid.uuid4().hex
    ctx = RequestContext(trace_id=trace_id, request_id=trace_id, user_id=user_id, session_id=session_id)
    answer = await runtime.run(ctx, message)
    return JSONResponse({"answer": answer, "trace_id": trace_id})


@app.get("/api/chat/stream")
async def chat_stream(message: str, session_id: str = "s1", user_id: str = "u"):
    async def gen():
        trace_id = uuid.uuid4().hex
        ctx = RequestContext(trace_id=trace_id, request_id=trace_id, user_id=user_id, session_id=session_id)
        answer = await runtime.run(ctx, message)
        yield f"data: {json.dumps({'answer': answer, 'trace_id': trace_id}, ensure_ascii=False)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.post("/api/kb/ingest")
async def ingest(req: Request) -> JSONResponse:
    body = await req.json()
    path = body.get("path", "")
    f = Path(path)
    if not f.exists() or f.suffix.lower() not in (".md", ".txt"):
        return JSONResponse({"error": "仅支持 .md/.txt 本地文件路径"}, status_code=400)
    chunks = chunk_text(parse_doc(str(f)))
    vector_store.add(f.stem, chunks, embed(chunks))
    return JSONResponse({"ingested": f.stem, "chunks": len(chunks)})


@app.get("/api/trace/{trace_id}")
def trace(trace_id: str) -> JSONResponse:
    events = trace_store.get(trace_id)
    return JSONResponse([e.__dict__ for e in events])


app.mount("/static", StaticFiles(directory=str(BASE / "webui")), name="static")
