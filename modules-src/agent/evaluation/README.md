# evaluation

RAG/Agent 评测：

- `ranking_metrics`：Recall@k、Precision@k、MRR@k、nDCG@k。
- `evaluate_qa`：检索指标与答案指标分开；词面重合是启发式，评审失败不补分。
- `llm_as_judge`：返回 `ok`/`unavailable` 状态，失败原因可追踪。
- `evaluate_agent`：工具正确率、任务成功率、平均延迟。

人工核验数据、实验命令和实际结果见仓库根目录的 `experiments/` 与 `docs/EXPERIMENTS.md`。
