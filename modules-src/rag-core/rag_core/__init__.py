from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from typing import Callable, List, Optional, Protocol, Tuple, Union, runtime_checkable

import numpy as np

from core_contracts import Citation, RequestContext, RetrievalResult

__version__ = "0.3.0"

DIM = 384
SearchHit = Tuple[str, str, float]
Scope = Union[str, List[str], None]
EmbedFunction = Callable[[List[str]], List[List[float]]]


def _tokens(text: str) -> List[str]:
    toks: List[str] = []
    for w in re.findall(r"[a-z0-9_]+", text.lower()):
        toks.append(w)
    for seg in re.findall(r"[\u4e00-\u9fff]+", text):
        toks.append(seg)
        for i in range(len(seg) - 1):
            toks.append(seg[i : i + 2])
    return toks


_FASTEMBED = "__unset__"
_DEFAULT_MODEL = "BAAI/bge-small-zh-v1.5"


def _embed_hash(texts: List[str]) -> List[List[float]]:
    out = []
    for t in texts:
        v = np.zeros(DIM, dtype=np.float32)
        for tok in _tokens(t):
            h = int(hashlib.sha1(tok.encode("utf-8")).hexdigest()[:8], 16)
            idx = h % DIM
            v[idx] += 1.0 if (h >> 8) & 1 else -1.0
        n = np.linalg.norm(v)
        if n > 0:
            v /= n
        out.append(v.tolist())
    return out


def _embed_fastembed(texts: List[str]) -> List[List[float]]:
    global _FASTEMBED
    if _FASTEMBED == "__unset__":
        model_name = os.environ.get("BGE_MODEL", _DEFAULT_MODEL).strip() or _DEFAULT_MODEL
        cache_dir = os.environ.get("FASTEMBED_CACHE_PATH", "").strip() or None
        try:
            from fastembed import TextEmbedding

            _FASTEMBED = TextEmbedding(model_name=model_name, cache_dir=cache_dir)
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "RAG 默认需要 fastembed，但当前 Python 环境未安装它；"
                "请安装 rag_core 依赖，或仅在明确需要无模型离线模式时设置 "
                "RAG_EMBED=hash"
            ) from exc
        except Exception as exc:
            raise RuntimeError(
                f"无法加载文本向量模型 {model_name}: {exc}"
            ) from exc
    try:
        return [list(map(float, v)) for v in _FASTEMBED.embed(texts)]
    except Exception as exc:
        model_name = os.environ.get("BGE_MODEL", _DEFAULT_MODEL).strip() or _DEFAULT_MODEL
        raise RuntimeError(f"文本向量模型 {model_name} 推理失败: {exc}") from exc


def embed(texts: List[str]) -> List[List[float]]:
    """默认用 FastEmbed 运行 BGE；hash 只能通过环境变量显式启用。"""
    backend = os.environ.get("RAG_EMBED", "fastembed").strip().lower()
    if backend == "fastembed":
        return _embed_fastembed(texts)
    if backend == "hash":
        return _embed_hash(texts)
    raise ValueError(f"不支持的 RAG_EMBED 后端: {backend!r}")


def make_embed(backend: str = "fastembed"):
    normalized = backend.strip().lower()
    if normalized == "fastembed":
        return _embed_fastembed
    if normalized == "hash":
        return _embed_hash
    raise ValueError(f"不支持的向量后端: {backend!r}")


@runtime_checkable
class VectorStore(Protocol):
    def add(self, source_id: str, chunks: List[str], embeddings) -> None: ...

    def search(
        self,
        embedding,
        top_k: int = 5,
        scopes: Optional[List[str]] = None,
    ) -> List[SearchHit]: ...


class InMemoryVectorStore:
    def __init__(self) -> None:
        self._rows: list[tuple[str, str, List[float]]] = []

    def add(self, source_id: str, chunks: List[str], embeddings) -> None:
        for text, emb in zip(chunks, embeddings):
            self._rows.append((source_id, text, emb))

    def search(
        self,
        embedding,
        top_k: int = 5,
        scopes: Optional[List[str]] = None,
    ) -> List[SearchHit]:
        q = np.array(embedding, dtype=np.float32)
        allowed = set(scopes) if scopes is not None else None
        rows = [row for row in self._rows if allowed is None or row[0].partition("/")[0] in allowed]
        scores = [float(np.dot(np.array(emb, dtype=np.float32), q)) for _, _, emb in rows]
        order = sorted(range(len(scores)), key=lambda i: -scores[i])[: min(top_k, len(scores))]
        return [(rows[i][0], rows[i][1], scores[i]) for i in order]


class SqliteVectorStore:
    """SQLite-backed vector store with the same facade as the in-memory store."""

    def __init__(self, db_path: str) -> None:
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS vectors (source_id TEXT, text TEXT, embedding TEXT)"
        )
        self._conn.commit()

    def add(self, source_id: str, chunks: List[str], embeddings) -> None:
        rows = [
            (source_id, text, json.dumps(list(map(float, embedding))))
            for text, embedding in zip(chunks, embeddings)
        ]
        self._conn.executemany(
            "INSERT INTO vectors (source_id, text, embedding) VALUES (?, ?, ?)",
            rows,
        )
        self._conn.commit()

    def search(
        self,
        embedding,
        top_k: int = 5,
        scopes: Optional[List[str]] = None,
    ) -> List[SearchHit]:
        allowed = set(scopes) if scopes is not None else None
        stored_rows = self._conn.execute(
            "SELECT source_id, text, embedding FROM vectors"
        ).fetchall()
        rows = [
            (source_id, text, json.loads(stored_embedding))
            for source_id, text, stored_embedding in stored_rows
            if allowed is None or source_id.partition("/")[0] in allowed
        ]
        query_vector = np.array(embedding, dtype=np.float32)
        scores = [
            float(np.dot(np.array(stored_embedding, dtype=np.float32), query_vector))
            for _, _, stored_embedding in rows
        ]
        order = sorted(range(len(scores)), key=lambda index: -scores[index])[
            : min(top_k, len(scores))
        ]
        return [(rows[index][0], rows[index][1], scores[index]) for index in order]


def _normalize_scopes(scope: Scope) -> Optional[List[str]]:
    if scope is None:
        return None
    if isinstance(scope, str):
        if scope in ("", "kb", "*"):
            return None
        return [item.strip() for item in scope.split(",") if item.strip()]
    return list(dict.fromkeys(item.strip() for item in scope if item.strip()))


def _result_from_hits(query: str, hits: List[SearchHit]) -> RetrievalResult:
    contexts = [text for _, text, _ in hits]
    citations = [
        Citation(
            source_id=source_id,
            title=source_id.partition("/")[2] or source_id,
            text=text,
            score=score,
            metadata={"knowledge_base_id": source_id.partition("/")[0]},
        )
        for source_id, text, score in hits
    ]
    return RetrievalResult(query=query, contexts=contexts, citations=citations)


class RagClient:
    def __init__(
        self,
        store: VectorStore,
        embed_fn: EmbedFunction = embed,
        top_k: int = 5,
    ) -> None:
        if top_k < 1:
            raise ValueError("top_k 必须大于 0")
        self.store = store
        self.embed_fn = embed_fn
        self.top_k = top_k

    def retrieve(
        self,
        ctx: RequestContext,
        query: str,
        scope: Scope = "kb",
        top_k: Optional[int] = None,
    ) -> RetrievalResult:
        limit = self.top_k if top_k is None else top_k
        if limit < 1:
            raise ValueError("top_k 必须大于 0")
        query_embedding = self.embed_fn([query])[0]
        hits = self.store.search(query_embedding, limit, _normalize_scopes(scope))
        return _result_from_hits(query, hits)


def retrieve(
    ctx: RequestContext,
    query: str,
    store: VectorStore,
    scope: Scope = "kb",
    top_k: int = 5,
) -> RetrievalResult:
    return RagClient(store=store, embed_fn=embed, top_k=top_k).retrieve(ctx, query, scope)


def build_context(result: RetrievalResult) -> str:
    if not result.contexts:
        return "(无相关文档)"
    blocks = []
    for index, context in enumerate(result.contexts):
        citation = result.citations[index] if index < len(result.citations) else None
        source = f" 来源：{citation.title}" if citation else ""
        blocks.append(f"[{index + 1}]{source}\n{context}")
    return "\n\n".join(blocks)


__all__ = [
    "DIM",
    "VectorStore",
    "InMemoryVectorStore",
    "SqliteVectorStore",
    "RagClient",
    "embed",
    "make_embed",
    "retrieve",
    "build_context",
]
