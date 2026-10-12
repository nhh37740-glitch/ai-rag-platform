# rag-facade

## 0.2.0
- RAGnotebook owns trace lifecycle through RagService; app no longer imports observability directly.

## 0.3.0 — 2026-10-12

- 在活动 embedding 后端或模型变化时，基于已存文本块原位重建向量。
- 将 embedding 模型标识记入现有 agent_data 表，不更改六表结构。
