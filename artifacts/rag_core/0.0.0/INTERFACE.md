# rag-core - 接口契约

## rag_core
```python
class VectorStore(Protocol):
    def add(self, source_id: str, chunks: list[str], embeddings) -> None: ...
    def search(self, embedding, top_k: int = 5) -> list[tuple[str, float]]: ...   # (source_id, score)

class InMemoryVectorStore:  # numpy 余弦相似度，离线
class SqliteVectorStore:    # 可选，SQLite + numpy

def embed(texts: list[str]) -> list[list[float]]: ...          # BGE 适配层；离线�?hash/均值兜�?def retrieve(ctx, query: str, scope: str = "kb", top_k: int = 5) -> RetrievalResult: ...
```

