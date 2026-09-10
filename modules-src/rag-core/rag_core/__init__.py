from __future__ import annotations

import hashlib
import os
import re
from typing import List, Optional, Tuple, Union

import numpy as np

from core_contracts import Citation, RequestContext, RetrievalResult

__version__ = "0.2.0"

DIM = 384


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
_MODEL = "BAAI/bge-small-zh-v1.5"


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
        try:
            from fastembed import TextEmbedding

            _FASTEMBED = TextEmbedding(model_name=_MODEL)
        except Exception:
            _FASTEMBED = False
    if not _FASTEMBED:
        raise RuntimeError("fastembed unavailable")
    return [list(map(float, v)) for v in _FASTEMBED.embed(texts)]


def embed(texts: List[str]) -> List[List[float]]:
    """向量化：env RAG_EMBED=fastembed 用真实多语言模型，否则用本地 hash 兜底。"""
    if os.environ.get("RAG_EMBED", "").lower() == "fastembed":
        try:
            return _embed_fastembed(texts)
        except Exception:
            pass
    return _embed_hash(texts)


def make_embed(backend: str = "hash"):
    if backend == "fastembed":
        return _embed_fastembed
    return _embed_hash


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
    ) -> List[Tuple[str, str, float]]:
        q = np.array(embedding, dtype=np.float32)
        allowed = set(scopes) if scopes is not None else None
        rows = [row for row in self._rows if allowed is None or row[0].partition("/")[0] in allowed]
        scores = [float(np.dot(np.array(emb, dtype=np.float32), q)) for _, _, emb in rows]
        order = sorted(range(len(scores)), key=lambda i: -scores[i])[: min(top_k, len(scores))]
        return [(rows[i][0], rows[i][1], scores[i]) for i in order]


def retrieve(
    ctx: RequestContext,
    query: str,
    store: InMemoryVectorStore,
    scope: Union[str, List[str], None] = "kb",
    top_k: int = 5,
) -> RetrievalResult:
    scopes: Optional[List[str]]
    if scope is None or scope in ("", "kb", "*"):
        scopes = None
    elif isinstance(scope, str):
        scopes = [item.strip() for item in scope.split(",") if item.strip()]
    else:
        scopes = list(dict.fromkeys(item.strip() for item in scope if item.strip()))
    qv = embed([query])[0]
    hits = store.search(qv, top_k, scopes)
    contexts = [text for _, text, _ in hits]
    citations = [
        Citation(
            source_id=sid,
            title=sid.partition("/")[2] or sid,
            text=text,
            score=score,
            metadata={"knowledge_base_id": sid.partition("/")[0]},
        )
        for sid, text, score in hits
    ]
    return RetrievalResult(query=query, contexts=contexts, citations=citations)


def build_context(result: RetrievalResult) -> str:
    if not result.contexts:
        return "(无相关文档)"
    blocks = []
    for index, context in enumerate(result.contexts):
        citation = result.citations[index] if index < len(result.citations) else None
        source = f" 来源：{citation.title}" if citation else ""
        blocks.append(f"[{index + 1}]{source}\n{context}")
    return "\n\n".join(blocks)


__all__ = ["embed", "make_embed", "InMemoryVectorStore", "retrieve", "build_context", "DIM"]
