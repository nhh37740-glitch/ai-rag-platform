from __future__ import annotations

# 运行边界必须最先建立：业务模块只允许从 artifacts 的编译产物加载。
import runtime_boundary

PUBLISHED_MODULES = runtime_boundary.enforce_binary_runtime()

from datetime import datetime, timezone
import asyncio
import hashlib
import ipaddress
import json
import os
import re
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from agent_runtime import AgentRuntime
from core_contracts import ChatMessage, RequestContext, ToolDef
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
from rag_core import SqliteVectorStore, embed
from rag_tools import RagTools
from request_provider import RequestScopedProvider
from skill_runtime import SkillRegistry
from tool_runtime import ToolRegistry

runtime_boundary.assert_binary_runtime(PUBLISHED_MODULES)

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[1]
KB_DIR = ROOT / "data" / "kb"
USER_NOTEBOOKS_DIR = KB_DIR / "user-notebooks"
AGENT_FILES_DIR = ROOT / "data" / "agent-files"
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


PUBLIC_DEMO = os.environ.get("PUBLIC_DEMO", "") == "1"
if not PUBLIC_DEMO:
    _load_dotenv(ROOT / ".env")

DEMO_KB_ID = "cmrc2018-demo" if PUBLIC_DEMO else os.environ.get("DEMO_KB_ID", "cmrc2018-demo")
DEMO_KB_DIR = KB_DIR / DEMO_KB_ID
STATE_DIR = Path(os.environ.get("STATE_DIR", str(ROOT / "data")))
DB_PATH = os.environ.get("DB_PATH", str(STATE_DIR / "app.db"))
API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
INDEX_PATH = os.environ.get("INDEX_PATH", str(STATE_DIR / "index.json"))

# 向量索引按 embedding 配置隔离，避免切换后端或模型后误用维度不兼容的旧向量。
# VECTOR_DB_PATH 可显式覆盖；默认路径稳定，因此服务重启会直接复用已有索引。
_embed_identity = "\0".join(
    (
        os.environ.get("RAG_EMBED", "fastembed").strip().lower(),
        os.environ.get("BGE_MODEL", "BAAI/bge-small-zh-v1.5").strip(),
    )
)
_embed_identity_hash = hashlib.sha256(_embed_identity.encode("utf-8")).hexdigest()[:12]
VECTOR_DB_PATH = os.environ.get(
    "VECTOR_DB_PATH",
    str(STATE_DIR / f"vector-index-{_embed_identity_hash}.sqlite"),
)

trace_store = make_trace_store()
memory = make_memory(":memory:" if PUBLIC_DEMO else DB_PATH)
skills = SkillRegistry()
skills.load_dir(str(SKILL_DIR))

DEMO_PROVIDER = os.environ.get("DEMO_PROVIDER", "mock").strip().lower()
if PUBLIC_DEMO:
    if DEMO_PROVIDER not in {"mock", "deepseek"}:
        raise RuntimeError("DEMO_PROVIDER 必须为 mock 或 deepseek")
    if DEMO_PROVIDER == "deepseek" and not API_KEY.strip():
        raise RuntimeError("公开 DeepSeek 演示缺少服务器凭据")
    provider = DeepSeekProvider(API_KEY, BASE_URL, MODEL) if DEMO_PROVIDER == "deepseek" else MockProvider("qa")
else:
    provider = DeepSeekProvider(API_KEY, BASE_URL, MODEL) if API_KEY else MockProvider("qa")
request_provider = RequestScopedProvider(provider, BASE_URL, MODEL)
tools = ToolRegistry()


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


def _create_user_notebook(name: str, description: str = "") -> tuple[Path, dict]:
    clean_name = name.strip()
    clean_description = description.strip()
    if not clean_name or len(clean_name) > 80:
        raise ValueError("笔记本名称长度应为 1-80 个字符")
    if len(clean_description) > 300:
        raise ValueError("笔记本说明不能超过 300 个字符")
    notebook_id = f"notebook-{uuid.uuid4().hex[:12]}"
    notebook_dir = _user_notebook_path(notebook_id)
    (notebook_dir / "markdown-documents").mkdir(parents=True)
    metadata = {
        "id": notebook_id,
        "name": clean_name,
        "description": clean_description,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "documents": [],
    }
    _write_user_notebook(notebook_dir, metadata)
    return notebook_dir, metadata


EMBED_BATCH_SIZE = 64

# upload_id -> {state, stage, done, total, message}，供前端轮询进度。
UPLOAD_PROGRESS: dict[str, dict] = {}


def _content_fingerprint(markdown: str) -> str:
    return hashlib.sha256(markdown.encode("utf-8")).hexdigest()


def _embed_in_batches(chunks: list[str], on_progress=None) -> list:
    """分批向量化：既能报告进度，也避免一次性把上千个块压进内存。"""
    embeddings: list = []
    total = len(chunks)
    for start in range(0, total, EMBED_BATCH_SIZE):
        batch = chunks[start : start + EMBED_BATCH_SIZE]
        embeddings.extend(embed(batch))
        if on_progress is not None:
            on_progress(min(start + len(batch), total), total)
    return embeddings


def _add_markdown_document(
    notebook_dir: Path,
    metadata: dict,
    original_name: str,
    markdown: str,
    progress: dict | None = None,
) -> dict:
    def report(stage: str, done: int = 0, total: int = 0, message: str = "") -> None:
        if progress is not None:
            progress.update(
                {"state": "running", "stage": stage, "done": done, "total": total, "message": message}
            )

    fingerprint = _content_fingerprint(markdown)
    for existing in metadata.get("documents", []):
        if existing.get("fingerprint") == fingerprint:
            raise ValueError(
                f"{original_name}: 这个文件已经导入过（{existing.get('title', '')}），没有重复入库"
            )

    safe_stem = re.sub(
        r"[^\w\u4e00-\u9fff-]+", "-", Path(original_name).stem
    ).strip("-_")[:60] or "document"
    markdown_file = f"{safe_stem}-{uuid.uuid4().hex[:8]}.md"
    markdown_path = notebook_dir / "markdown-documents" / markdown_file
    report("写入 Markdown", 0, 0, original_name)
    markdown_path.write_text(markdown, encoding="utf-8")
    try:
        report("切分文本", 0, 0, original_name)
        chunks = chunk_text(parse_doc(str(markdown_path)))
        if not chunks:
            raise ValueError("文档中没有可入库的文本")
        embeddings = _embed_in_batches(
            chunks,
            lambda done, total: report("向量化", done, total, original_name),
        )
        report("写入索引", 0, 0, original_name)
        source_id = f"{metadata['id']}/{markdown_path.stem}"
        vector_store.add(source_id, chunks, embeddings)
    except Exception:
        markdown_path.unlink(missing_ok=True)
        raise
    document = {
        "original_name": original_name,
        "markdown_file": markdown_file,
        "title": Path(original_name).stem,
        "chunks": len(chunks),
        "fingerprint": fingerprint,
    }
    metadata["documents"].append(document)
    _write_user_notebook(notebook_dir, metadata)
    return document


def _conversation_markdown(name: str, messages: list[ChatMessage]) -> str:
    sections = [f"# {name.strip()}", ""]
    labels = {"user": "用户", "assistant": "Agent"}
    for message in messages:
        content = (message.content or "").strip()
        if message.role not in labels or not content:
            continue
        sections.extend([f"## {labels[message.role]}", "", content, ""])
    if len(sections) == 2:
        raise ValueError("当前会话没有可保存的内容")
    return "\n".join(sections).rstrip() + "\n"


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


def _load_kb() -> tuple[SqliteVectorStore, int]:
    store = SqliteVectorStore(VECTOR_DB_PATH)
    loaded_sources = {
        source_id for source_id, _ in store.list_documents([DEMO_KB_ID] if PUBLIC_DEMO else None)
    }

    # 兼容旧版 JSON 索引：若存在且 embedding 配置一致，只迁移数据库中缺失的来源。
    index = Path(INDEX_PATH)
    if not PUBLIC_DEMO and index.exists():
        data = json.loads(index.read_text(encoding="utf-8"))
        if data.get("embed", "__unknown__") == os.environ.get("RAG_EMBED", "hash"):
            for s in data.get("sources", []):
                if s["id"] in loaded_sources:
                    continue
                store.add(s["id"], s["chunks"], s["embs"])
                loaded_sources.add(s["id"])
    files = [] if PUBLIC_DEMO else sorted(f for f in KB_DIR.glob("*.md") if f.name.lower() != "readme.md")
    for f in files:
        source_id = f"local-documents/{f.stem}"
        if source_id in loaded_sources:
            continue
        chunks = chunk_text(parse_doc(str(f)))
        store.add(source_id, chunks, _embed_in_batches(chunks))
        loaded_sources.add(source_id)

    _, demo_documents = _load_demo_knowledge_base()
    imported = 0
    for path, _ in demo_documents:
        source_id = f"{DEMO_KB_ID}/{path.stem}"
        if source_id in loaded_sources:
            imported += 1
            continue
        chunks = chunk_text(parse_doc(str(path)))
        store.add(source_id, chunks, _embed_in_batches(chunks))
        loaded_sources.add(source_id)
        imported += 1

    for notebook_dir, metadata in ([] if PUBLIC_DEMO else _list_user_notebooks()):
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
            store.add(source_id, chunks, _embed_in_batches(chunks))
            loaded_sources.add(source_id)
    return store, imported


vector_store, demo_kb_imported = _load_kb()

rag_tools = RagTools(vector_store, trace_store)


def _knowledge_base_scope(runtime_context: dict | None) -> list[str]:
    """检索范围只能来自当前请求，LLM 无法通过工具参数扩大。"""
    if PUBLIC_DEMO:
        return [DEMO_KB_ID]
    if runtime_context is None:
        raise ValueError("缺少工具运行上下文")
    return runtime_context.get("knowledge_base_ids", [])


def _search_knowledge_base(
    query: str,
    top_k: int | None = None,
    *,
    ctx: RequestContext,
    runtime_context: dict | None,
) -> str:
    return rag_tools.search(ctx, query, _knowledge_base_scope(runtime_context), top_k)


def _hybrid_search_knowledge_base(
    query: str,
    top_k: int | None = None,
    *,
    ctx: RequestContext,
    runtime_context: dict | None,
) -> str:
    return rag_tools.hybrid_search(ctx, query, _knowledge_base_scope(runtime_context), top_k)


def _keyword_search_knowledge_base(
    query: str,
    top_k: int | None = None,
    *,
    ctx: RequestContext,
    runtime_context: dict | None,
) -> str:
    return rag_tools.keyword_search(ctx, query, _knowledge_base_scope(runtime_context), top_k)


def _list_knowledge_documents(
    *,
    ctx: RequestContext,
    runtime_context: dict | None,
) -> str:
    return rag_tools.list_documents(ctx, _knowledge_base_scope(runtime_context))


def _read_knowledge_document(
    source_id: str,
    offset: int = 0,
    max_chunks: int | None = None,
    *,
    ctx: RequestContext,
    runtime_context: dict | None,
) -> str:
    return rag_tools.read_document(ctx, source_id, _knowledge_base_scope(runtime_context), offset, max_chunks)


def _create_agent_file(filename: str, content: str) -> str:
    if not isinstance(filename, str) or not filename.strip():
        raise ValueError("文件名不能为空")
    clean_name = filename.strip()
    if clean_name != Path(clean_name).name:
        raise ValueError("文件名不能包含路径")
    if Path(clean_name).suffix.lower() not in {".md", ".txt", ".json"}:
        raise ValueError("只允许创建 .md、.txt 或 .json 文件")
    if not isinstance(content, str) or len(content.encode("utf-8")) > 1024 * 1024:
        raise ValueError("文件内容必须是不超过 1 MiB 的文本")
    AGENT_FILES_DIR.mkdir(parents=True, exist_ok=True)
    path = (AGENT_FILES_DIR / clean_name).resolve()
    if AGENT_FILES_DIR.resolve() not in path.parents:
        raise ValueError("文件路径超出允许范围")
    if path.exists():
        raise FileExistsError(f"文件已存在: {clean_name}")
    path.write_text(content, encoding="utf-8")
    return json.dumps(
        {"created": True, "filename": clean_name, "path": f"data/agent-files/{clean_name}"},
        ensure_ascii=False,
    )


def _save_conversation_to_knowledge_base(
    name: str,
    description: str = "",
    *,
    ctx: RequestContext,
    runtime_context: dict | None,
) -> str:
    if runtime_context is None:
        raise ValueError("缺少工具运行上下文")
    messages = runtime_context.get("messages", [])
    markdown = _conversation_markdown(name, messages)
    notebook_dir, metadata = _create_user_notebook(name, description)
    try:
        document = _add_markdown_document(
            notebook_dir,
            metadata,
            "conversation.md",
            markdown,
        )
    except Exception:
        metadata["description"] = (
            metadata.get("description", "") + " [创建后入库失败]"
        ).strip()
        _write_user_notebook(notebook_dir, metadata)
        raise
    selected_ids = runtime_context.setdefault("knowledge_base_ids", [])
    if metadata["id"] not in selected_ids:
        selected_ids.append(metadata["id"])
    return json.dumps(
        {
            "created": True,
            "knowledge_base": _public_notebook(metadata, True),
            "document": document,
        },
        ensure_ascii=False,
    )


KNOWLEDGE_BASE_TOOL_HANDLERS = {
    "search_knowledge_base": _search_knowledge_base,
    "hybrid_search_knowledge_base": _hybrid_search_knowledge_base,
    "keyword_search_knowledge_base": _keyword_search_knowledge_base,
    "list_knowledge_documents": _list_knowledge_documents,
    "read_knowledge_document": _read_knowledge_document,
}

for tool_definition in rag_tools.tool_definitions():
    knowledge_base_handler = KNOWLEDGE_BASE_TOOL_HANDLERS.get(tool_definition.name)
    if knowledge_base_handler is None:
        raise RuntimeError(f"知识库工具缺少执行函数: {tool_definition.name}")
    tools.register(tool_definition, knowledge_base_handler, context_aware=True)

def _register_private_tool(*args, **kwargs) -> None:
    if not PUBLIC_DEMO:
        tools.register(*args, **kwargs)


_register_private_tool(
    ToolDef(
        "create_file",
        "在受限的 data/agent-files 目录创建新文本文件；不能覆盖已有文件或写入仓库其他位置。",
        {
            "type": "object",
            "properties": {
                "filename": {"type": "string", "description": "带 .md/.txt/.json 后缀的文件名"},
                "content": {"type": "string", "description": "要写入的文本内容"},
            },
            "required": ["filename", "content"],
            "additionalProperties": False,
        },
    ),
    _create_agent_file,
)
_register_private_tool(
    ToolDef(
        "save_conversation_to_knowledge_base",
        "当用户明确要求保存当前对话时，将截至调用时的用户与 Agent 消息转为 Markdown，创建新笔记本并立即入库。",
        {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "新知识库名称"},
                "description": {"type": "string", "description": "新知识库说明"},
            },
            "required": ["name"],
            "additionalProperties": False,
        },
    ),
    _save_conversation_to_knowledge_base,
    context_aware=True,
)

runtime = AgentRuntime(
    provider=request_provider,
    memory=memory,
    tools=tools,
    skills=skills,
    tracing=trace_store,
    max_tool_rounds=10,
)

app = FastAPI(title="Dev Knowledge Agent")


@app.get("/")
def index() -> FileResponse:
    filename = "public_demo.html" if PUBLIC_DEMO else "index.html"
    return FileResponse(str(BASE / "webui" / filename))


def _demo_suggested_questions() -> list[dict]:
    manifest, documents = _load_demo_knowledge_base()
    document_items = {item.get("file"): item for _, item in documents}
    suggested: list[dict] = []
    for suggestion in manifest.get("featured_questions", []):
        if not isinstance(suggestion, dict):
            continue
        document = document_items.get(suggestion.get("document"))
        question = suggestion.get("question", "")
        if not document or question not in document.get("questions", []):
            continue
        suggested.append(
            {
                "question": question,
                "topic": suggestion.get("topic", "知识库"),
                "title": document.get("title", Path(document["file"]).stem),
            }
        )
    return suggested


_CHAPTER_PATTERN = re.compile(r"^第\s*[0-9一二三四五六七八九十百千零两]+\s*[章节回卷部篇]")
TOPIC_LABEL_MAX = 12
TOPIC_LABEL_MIN = 4


def _topic_candidates(markdown_path: Path, limit: int = 4, skip: str = "") -> list[str]:
    """从 Markdown 里挑出可提问的主题：优先章节行，其次短标签行。"""
    try:
        text = markdown_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []

    chapters: list[str] = []
    labels: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip().lstrip("#").strip().rstrip("：:").strip()
        if not line or len(line) > 40:
            continue
        if skip and line == skip:  # 文档标题本身不算主题
            continue
        if _CHAPTER_PATTERN.match(line):
            if line not in chapters:
                chapters.append(line)
        elif TOPIC_LABEL_MIN <= len(line) <= TOPIC_LABEL_MAX and not line.endswith(
            ("。", "！", "？", ".", "!", "?")
        ):
            if line not in labels:
                labels.append(line)

    topics: list[str] = []
    for pool in (chapters, labels):
        for item in pool:
            if item not in topics:
                topics.append(item)
            if len(topics) >= limit:
                return topics
    return topics


@app.get("/api/demo")
def demo() -> JSONResponse:
    manifest, documents = _load_demo_knowledge_base()
    questions = [
        question
        for _, item in documents
        for question in item.get("questions", [])
        if isinstance(question, str) and question.strip()
    ]
    return JSONResponse(
        {
            "id": manifest.get("id", DEMO_KB_ID),
            "name": manifest.get("name", DEMO_KB_ID),
            "source": manifest.get("source", ""),
            "license": manifest.get("license", ""),
            "documents": len(documents),
            "questions": questions,
            "question_count": len(questions),
            "suggested_questions": _demo_suggested_questions(),
            "imported": demo_kb_imported,
            "knowledge_base": "data/kb/cmrc2018-demo",
            "purpose": "project-demo-only",
            "public_demo": PUBLIC_DEMO,
            "read_only": PUBLIC_DEMO,
            "provider": DEMO_PROVIDER if PUBLIC_DEMO else ("deepseek" if API_KEY else "mock"),
            "embedding": os.environ.get("RAG_EMBED", "fastembed").strip().lower(),
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


@app.get("/api/notebooks/{notebook_id}/documents")
def notebook_documents(notebook_id: str) -> JSONResponse:
    """列出某个笔记本收录的文档，供前端展示来源列表。"""
    counts = dict(vector_store.list_documents([notebook_id]))

    if notebook_id == DEMO_KB_ID:
        manifest, documents = _load_demo_knowledge_base()
        items = []
        for path, item in documents:
            source_id = f"{DEMO_KB_ID}/{path.stem}"
            items.append(
                {
                    "title": item.get("title") or path.stem,
                    "source_id": source_id,
                    "chunks": counts.get(source_id, 0),
                }
            )
        return JSONResponse(
            {
                "notebook_id": DEMO_KB_ID,
                "name": manifest.get("name", DEMO_KB_ID),
                "writable": False,
                "documents": items,
            }
        )

    try:
        notebook_dir = _user_notebook_path(notebook_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    metadata = _read_user_notebook(notebook_dir)
    if not metadata:
        raise HTTPException(status_code=404, detail="笔记本不存在")

    items = []
    for document in metadata.get("documents", []):
        markdown_file = document.get("markdown_file", "")
        if not markdown_file:
            continue
        stem = Path(markdown_file).stem
        source_id = f"{notebook_id}/{stem}"
        items.append(
            {
                "title": document.get("title") or stem,
                "source_id": source_id,
                "chunks": counts.get(source_id, 0),
            }
        )
    return JSONResponse(
        {
            "notebook_id": notebook_id,
            "name": metadata.get("name", notebook_id),
            "writable": True,
            "documents": items,
        }
    )


@app.get("/api/notebooks/{notebook_id}/suggestions")
def notebook_suggestions(notebook_id: str) -> JSONResponse:
    """针对该笔记本的实际内容生成示例问题，而不是套用演示语料的问题。"""
    if notebook_id == DEMO_KB_ID:
        return JSONResponse(
            {
                "notebook_id": DEMO_KB_ID,
                "source": "curated",
                "questions": _demo_suggested_questions(),
            }
        )

    try:
        notebook_dir = _user_notebook_path(notebook_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    metadata = _read_user_notebook(notebook_dir)
    if not metadata:
        raise HTTPException(status_code=404, detail="笔记本不存在")

    documents_dir = notebook_dir / "markdown-documents"
    questions: list[dict] = []
    for document in metadata.get("documents", []):
        markdown_file = document.get("markdown_file", "")
        title = document.get("title") or Path(markdown_file).stem
        if not title:
            continue
        questions.append({"question": f"《{title}》主要讲了什么？", "topic": "全文", "title": title})
        if not markdown_file:
            continue
        for topic in _topic_candidates(
            documents_dir / Path(markdown_file).name, limit=4, skip=title
        ):
            questions.append(
                {"question": f"「{topic}」这部分写了什么？", "topic": "内容", "title": title}
            )

    return JSONResponse(
        {
            "notebook_id": notebook_id,
            "source": "content",
            "questions": questions[:8],
        }
    )


@app.post("/api/notebooks")
async def create_notebook(req: Request) -> JSONResponse:
    body = await req.json()
    name = str(body.get("name", "")).strip()
    description = str(body.get("description", "")).strip()
    try:
        _, metadata = _create_user_notebook(name, description)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse(_public_notebook(metadata, True), status_code=201)


@app.post("/api/notebooks/{notebook_id}/files")
async def upload_notebook_files(
    notebook_id: str,
    files: list[UploadFile] = File(...),
    upload_id: str = "",
) -> JSONResponse:
    try:
        notebook_dir = _user_notebook_path(notebook_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    metadata = _read_user_notebook(notebook_dir)
    if not metadata:
        raise HTTPException(status_code=404, detail="笔记本不存在")

    progress = UPLOAD_PROGRESS.setdefault(upload_id, {}) if upload_id else None

    def update(**fields) -> None:
        if progress is not None:
            progress.update(fields)

    try:
        update(state="running", stage="转换文件", done=0, total=0, message="")
        converted = await convert_uploaded_documents(files)
    except UploadValidationError as exc:
        update(state="error", stage="失败", message=str(exc))
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    imported: list[dict] = []
    try:
        for index, (original_name, markdown) in enumerate(converted, start=1):
            update(
                state="running",
                stage=f"入库 {index}/{len(converted)}",
                done=0,
                total=0,
                message=original_name,
            )
            # 向量化是 CPU 密集的同步调用，必须离开事件循环，否则整个服务在
            # 处理大文件期间会毫无响应。
            document = await asyncio.to_thread(
                _add_markdown_document,
                notebook_dir,
                metadata,
                original_name,
                markdown,
                progress,
            )
            imported.append(document)
    except ValueError as exc:
        update(state="error", stage="失败", message=str(exc))
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - 兜底，保证前端能看到失败
        update(state="error", stage="失败", message=f"{type(exc).__name__}: {exc}")
        raise

    update(
        state="done",
        stage="完成",
        done=1,
        total=1,
        message=f"已导入 {len(imported)} 篇来源",
    )
    return JSONResponse({"notebook_id": notebook_id, "imported": imported}, status_code=201)


@app.get("/api/uploads/{upload_id}")
def upload_status(upload_id: str) -> JSONResponse:
    record = UPLOAD_PROGRESS.get(upload_id)
    if record is None:
        raise HTTPException(status_code=404, detail="没有这个上传任务")
    return JSONResponse({"upload_id": upload_id, **record})


def _is_loopback_host(host: str) -> bool:
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _web_key_origin_allowed(req: Request) -> bool:
    # Validate the browser-facing origin, since TLS may terminate at a local proxy.
    origin = req.headers.get("origin", "")
    try:
        parsed = urlsplit(origin)
        host = parsed.hostname or ""
    except ValueError:
        return False
    if parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password:
        return False
    if parsed.netloc.lower() != req.headers.get("host", "").lower():
        return False
    return parsed.scheme == "https" or (parsed.scheme == "http" and _is_loopback_host(host))


@app.post("/api/chat")
async def chat(req: Request) -> JSONResponse:
    api_key = req.headers.get("x-deepseek-api-key")
    if api_key is not None and not _web_key_origin_allowed(req):
        raise HTTPException(status_code=403, detail="个人 API Key 仅允许通过 HTTPS 或本机页面使用")
    body = await req.json()
    user_id = body.get("user_id", "anon")
    session_id = body.get("session_id", "s1")
    message = body.get("message", "")
    knowledge_base_ids = _selected_notebook_ids(body.get("knowledge_base_ids"))
    trace_id = uuid.uuid4().hex
    ctx = RequestContext(trace_id=trace_id, request_id=trace_id, user_id=user_id, session_id=session_id)
    if api_key is not None and (not api_key.strip() or len(api_key) > 512):
        raise HTTPException(status_code=422, detail="无效的 DeepSeek API Key")
    with request_provider.use_key(api_key.strip() if api_key else None):
        answer = await runtime.run(ctx, message, knowledge_base_ids)
    return JSONResponse(
        {"answer": answer, "trace_id": trace_id, "knowledge_base_ids": knowledge_base_ids},
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/llm/config")
def llm_config() -> JSONResponse:
    return JSONResponse(
        {"server_key_configured": bool(API_KEY), "model": MODEL},
        headers={"Cache-Control": "no-store"},
    )


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
    if PUBLIC_DEMO:
        return JSONResponse(public_demo.trace(trace_id), headers={"Cache-Control": "no-store"})
    events = trace_store.get(trace_id)
    return JSONResponse([e.__dict__ for e in events])


if PUBLIC_DEMO:
    from public_demo import PublicDemo, PublicDemoBoundary

    # Each invocation owns its history and an ephemeral memory module. The five
    # registered tools still execute the actual published RAG module facades.
    public_demo = PublicDemo(
        runtime_factory=lambda: AgentRuntime(
            provider=provider, memory=make_memory(":memory:"), tools=tools,
            skills=skills, tracing=trace_store, max_tool_rounds=10,
        ),
        tracing=trace_store,
        questions=[item["question"] for item in _demo_suggested_questions()],
        provider=DEMO_PROVIDER,
        embedding=os.environ.get("RAG_EMBED", "fastembed").strip().lower(),
        kb_id=DEMO_KB_ID,
    )
    app.add_middleware(PublicDemoBoundary)


@app.post("/api/demo/chat")
async def demo_chat(req: Request) -> JSONResponse:
    if not PUBLIC_DEMO:
        raise HTTPException(status_code=404, detail="公开演示未启用")
    return await public_demo.chat(req)


app.mount("/static", StaticFiles(directory=str(BASE / "webui")), name="static")
