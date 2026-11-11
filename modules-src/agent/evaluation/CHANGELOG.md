# 0.2.0
- 新增 `ranking_metrics`：Recall@k、Precision@k、MRR@k、nDCG@k，支持显式截断和分级相关性；Precision@k 固定以请求的 k 为分母。
- `evaluate_qa` 返回结构化的 `retrieval` 与 `answer`，词面重合明确标注为启发式。
- `llm_as_judge` 改为返回状态字典；失败、空响应、不可解析或越界分数返回 `unavailable`，不再按答案长度补分。
- `answer_relevance` 只在评审成功时提供，避免把长度启发式当成质量分数。

# 0.1.1
- 共享接口包迁移为 core_specifications；重新构建二进制并保持本模块接口行为。

# Changelog

## [0.0.0]
- 初始化版本。
