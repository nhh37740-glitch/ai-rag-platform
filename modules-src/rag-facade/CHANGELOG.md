## 0.3.2 - 2026-10-13

## 0.3.3 — 2026-10-13

- 导入支持阶段与分块进度回调，向量分批计算完成后原子入库。

- Build the complete new embedding set before a single atomic replacement.

# rag-facade

## 0.2.0
- RAGnotebook owns trace lifecycle through RagService; app no longer imports observability directly.

## 0.3.0 — 2026-10-12

- 在活动 embedding 后端或模型变化时，基于已存文本块原位重建向量。
- 将 embedding 模型标识记入现有 agent_data 表，不更改六表结构。

## 0.3.1 — 2026-10-13

- 修复启动时读取 embedding 后端配置缺少 os 导入的问题。
