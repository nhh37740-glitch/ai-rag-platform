from __future__ import annotations

import hashlib
import os
import re
from typing import List, Tuple

import numpy as np

from core_contracts import Citation, RequestContext, RetrievalResult

__version__ = "0.1.0"

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
_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


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

    def search(self, embedding, top_k: int = 5) -> List[Tuple[str, str, float]]:
        q = np.array(embedding, dtype=np.float32)
        scores = [float(np.dot(np.array(emb, dtype=np.float32), q)) for _, _, emb in self._rows]
        order = sorted(range(len(scores)), key=lambda i: -scores[i])[: min(top_k, len(scores))]
        return [(self._rows[i][0], self._rows[i][1], scores[i]) for i in order]


def retrieve(ctx: RequestContext, query: str, store: InMemoryVectorStore, scope: str = "kb", top_k: int = 5) -> RetrievalResult:
    qv = embed([query])[0]
    hits = store.search(qv, top_k)
    contexts = [text for _, text, _ in hits]
    citations = [Citation(source_id=sid, title=sid, text=text, score=score) for sid, text, score in hits]
    return RetrievalResult(query=query, contexts=contexts, citations=citations)


def build_context(result: RetrievalResult) -> str:
    if not result.contexts:
        return "(无相关文档)"
    return "\n\n".join(f"[{i+1}] {c}" for i, c in enumerate(result.contexts))


__all__ = ["embed", "make_embed", "InMemoryVectorStore", "retrieve", "build_context", "DIM"]
