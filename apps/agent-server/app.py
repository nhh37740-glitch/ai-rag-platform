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
KB_DIR = BASE / ".." / ".." / "data" / "kb"
SKILL_DIR = BASE / ".." / ".." / "skills"
DB_PATH = os.environ.get("DB_PATH", str(BASE / ".." / ".." / "data" / "app.db"))
API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
INDEX_PATH = os.environ.get("INDEX_PATH", str(BASE / ".." / ".." / "data" / "index.json"))

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


def _load_kb() -> InMemoryVectorStore:
    store = InMemoryVectorStore()
    index = Path(INDEX_PATH)
    if index.exists():
        data = json.loads(index.read_text(encoding="utf-8"))
        for s in data.get("sources", []):
            store.add(s["id"], s["chunks"], s["embs"])
        return store
    files = sorted(KB_DIR.glob("*.md"))
    for f in files:
        chunks = chunk_text(parse_doc(str(f)))
        store.add(f.stem, chunks, embed(chunks))
    return store


vector_store = _load_kb()

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
