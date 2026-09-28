from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from typing import Callable, Dict, List, Optional, Protocol, Tuple, Union, runtime_checkable

import numpy as np

from core_contracts import Citation, RequestContext, RetrievalResult

__version__ = "0.4.1"

DIM = 384
SearchHit = Tuple[str, str, float]
Scope = Union[str, List[str], None]
EmbedFunction = Callable[[List[str]], List[List[float]]]

# read_document 的分页约束：一次调用绝不能读回整篇长文档。
DEFAULT_READ_CHUNKS = 20
MAX_READ_CHUNKS = 100


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

    def list_documents(self, scopes: Optional[List[str]] = None) -> List[Tuple[str, int]]: ...

    def document_chunks(self, source_id: str) -> List[str]: ...


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

    def list_documents(self, scopes: Optional[List[str]] = None) -> List[Tuple[str, int]]:
        allowed = set(scopes) if scopes is not None else None
        counts: Dict[str, int] = {}
        for source_id, _text, _emb in self._rows:
            if allowed is not None and source_id.partition("/")[0] not in allowed:
                continue
            counts[source_id] = counts.get(source_id, 0) + 1
        return sorted(counts.items())

    def document_chunks(self, source_id: str) -> List[str]:
        return [text for row_source, text, _emb in self._rows if row_source == source_id]


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

    def list_documents(self, scopes: Optional[List[str]] = None) -> List[Tuple[str, int]]:
        allowed = set(scopes) if scopes is not None else None
        counts: Dict[str, int] = {}
        stored = self._conn.execute(
            "SELECT source_id FROM vectors ORDER BY rowid"
        ).fetchall()
        for (source_id,) in stored:
            if allowed is not None and source_id.partition("/")[0] not in allowed:
                continue
            counts[source_id] = counts.get(source_id, 0) + 1
        return sorted(counts.items())

    def document_chunks(self, source_id: str) -> List[str]:
        stored = self._conn.execute(
            "SELECT text FROM vectors WHERE source_id = ? ORDER BY rowid",
            (source_id,),
        ).fetchall()
        return [text for (text,) in stored]


def _normalize_scopes(scope: Scope) -> Optional[List[str]]:
    if scope is None:
        return None
    if isinstance(scope, str):
        if scope in ("", "kb", "*"):
            return None
        return [item.strip() for item in scope.split(",") if item.strip()]
    return list(dict.fromkeys(item.strip() for item in scope if item.strip()))


def _require_query(query: str) -> str:
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query 不能为空")
    return query.strip()


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


def _token_weights(query: str) -> Dict[str, float]:
    """把查询拆成带权重的词元：英文词与中文双字权重高，整段中文权重低。"""
    weights: Dict[str, float] = {}
    for word in re.findall(r"[a-z0-9_]+", query.lower()):
        weights[word] = max(weights.get(word, 0.0), 1.0)
    for segment in re.findall(r"[\u4e00-\u9fff]+", query):
        if len(segment) >= 2:
            weights[segment] = max(weights.get(segment, 0.0), 0.5)
        for index in range(len(segment) - 1):
            bigram = segment[index : index + 2]
            weights[bigram] = max(weights.get(bigram, 0.0), 1.0)
    return weights


def _keyword_score(query: str, text: str) -> float:
    """词面重合度，范围 [0,1]；不依赖任何向量模型。"""
    weights = _token_weights(query)
    total = sum(weights.values())
    if total <= 0:
        return 0.0
    lowered = text.lower()
    matched = sum(weight for token, weight in weights.items() if token in lowered)
    return matched / total


def _keyword_hits(
    query: str,
    store: VectorStore,
    scopes: Optional[List[str]],
    limit: int,
) -> List[SearchHit]:
    """对范围内全部文本块做词面打分；list_documents 已按 source_id 升序，同分保持稳定顺序。"""
    hits: List[SearchHit] = []
    for source_id, _chunk_count in store.list_documents(scopes):
        for chunk in store.document_chunks(source_id):
            score = _keyword_score(query, chunk)
            if score > 0.0:
                hits.append((source_id, chunk, score))
    hits.sort(key=lambda item: -item[2])
    return hits[:limit]


def keyword_search(
    ctx: RequestContext,
    query: str,
    store: VectorStore,
    scope: Scope = "kb",
    top_k: int = 5,
) -> RetrievalResult:
    """纯词面检索：不需要向量模型，专有名词与原文术语命中稳定。"""
    normalized = _require_query(query)
    if top_k < 1:
        raise ValueError("top_k 必须大于 0")
    scopes = _normalize_scopes(scope)
    return _result_from_hits(normalized, _keyword_hits(normalized, store, scopes, top_k))


def hybrid_search(
    ctx: RequestContext,
    query: str,
    store: VectorStore,
    scope: Scope = "kb",
    top_k: int = 5,
    alpha: float = 0.5,
) -> RetrievalResult:
    """向量与词面的融合检索：RRF 合并两路排名，避免语义模型漏掉原文术语。"""
    normalized = _require_query(query)
    if top_k < 1:
        raise ValueError("top_k 必须大于 0")
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha 必须在 0 和 1 之间")
    scopes = _normalize_scopes(scope)
    pool_size = max(top_k * 4, 20)

    query_embedding = embed([normalized])[0]
    vector_hits = store.search(query_embedding, pool_size, scopes)
    keyword_hits = _keyword_hits(normalized, store, scopes, pool_size)

    fused: Dict[Tuple[str, str], float] = {}
    for rank, (source_id, text, _score) in enumerate(vector_hits, start=1):
        key = (source_id, text)
        fused[key] = fused.get(key, 0.0) + (1.0 - alpha) / (60.0 + rank)
    for rank, (source_id, text, _score) in enumerate(keyword_hits, start=1):
        key = (source_id, text)
        fused[key] = fused.get(key, 0.0) + alpha / (60.0 + rank)

    ordered = sorted(fused.items(), key=lambda item: (-item[1], item[0][0]))
    hits = [(source_id, text, score) for (source_id, text), score in ordered[:top_k]]
    return _result_from_hits(normalized, hits)


def list_documents(ctx: RequestContext, store: VectorStore, scope: Scope = "kb") -> List[dict]:
    """列出范围内的文档清单，供 Agent 在检索不到时确认知识库里到底有什么。"""
    scopes = _normalize_scopes(scope)
    documents: List[dict] = []
    for source_id, chunk_count in store.list_documents(scopes):
        documents.append(
            {
                "source_id": source_id,
                "title": source_id.partition("/")[2] or source_id,
                "knowledge_base_id": source_id.partition("/")[0],
                "chunk_count": int(chunk_count),
            }
        )
    return documents


def document_info(ctx: RequestContext, store: VectorStore, source_id: str) -> dict:
    """单篇文档的元信息：{source_id,title,knowledge_base_id,chunk_count}。

    source_id 不存在时 chunk_count 为 0，供调用方判断该如何分页。
    """
    if not isinstance(source_id, str) or not source_id.strip():
        raise ValueError("source_id 不能为空")
    normalized = source_id.strip()
    return {
        "source_id": normalized,
        "title": normalized.partition("/")[2] or normalized,
        "knowledge_base_id": normalized.partition("/")[0],
        "chunk_count": len(store.document_chunks(normalized)),
    }


def read_document(
    ctx: RequestContext,
    store: VectorStore,
    source_id: str,
    max_chunks: int = DEFAULT_READ_CHUNKS,
    offset: int = 0,
) -> RetrievalResult:
    """分页读取文档原文，用于定位到目标文档后核对内容。

    一次调用最多返回 ``max_chunks`` 块（上限 ``MAX_READ_CHUNKS``），因此不可能把
    整篇长文档一次读回。每个引用的 ``metadata`` 会带上该块在全文中的 ``chunk_index``
    与 ``total_chunks``，调用方据此决定是否用更大的 ``offset`` 续读。
    """
    if not isinstance(source_id, str) or not source_id.strip():
        raise ValueError("source_id 不能为空")
    if isinstance(max_chunks, bool) or not isinstance(max_chunks, int):
        raise TypeError("max_chunks 必须是整数")
    if max_chunks < 1 or max_chunks > MAX_READ_CHUNKS:
        raise ValueError(f"max_chunks 必须在 1 到 {MAX_READ_CHUNKS} 之间")
    if isinstance(offset, bool) or not isinstance(offset, int):
        raise TypeError("offset 必须是整数")
    if offset < 0:
        raise ValueError("offset 不能为负数")

    normalized = source_id.strip()
    all_chunks = store.document_chunks(normalized)
    total_chunks = len(all_chunks)
    page = all_chunks[offset : offset + max_chunks]
    hits: List[SearchHit] = [(normalized, chunk, 1.0) for chunk in page]
    result = _result_from_hits(normalized, hits)
    knowledge_base_id = normalized.partition("/")[0]
    for chunk_index, citation in enumerate(result.citations, start=offset + 1):
        citation.metadata["chunk_index"] = chunk_index
        citation.metadata["total_chunks"] = total_chunks
    return result


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
    "DEFAULT_READ_CHUNKS",
    "MAX_READ_CHUNKS",
    "VectorStore",
    "InMemoryVectorStore",
    "SqliteVectorStore",
    "RagClient",
    "embed",
    "make_embed",
    "retrieve",
    "keyword_search",
    "hybrid_search",
    "list_documents",
    "document_info",
    "read_document",
    "build_context",
]
