from __future__ import annotations

import hashlib
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


def embed(texts: List[str]) -> List[List[float]]:
    """离线兜底向量化（BGE 适配层，接入 sentence-transformers 可替换）。"""
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


__all__ = ["embed", "InMemoryVectorStore", "retrieve", "build_context", "DIM"]
