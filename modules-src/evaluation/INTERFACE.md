# INTERFACE

- `ranking_metrics(relevant, retrieved, k=None, grades=None) -> dict`
  - 返回 `k`、`recall_at_k`、`precision_at_k`、`mrr_at_k`、`ndcg_at_k`。
  - `retrieved` 按相关度从高到低传入；重复项会保留首次出现位置。
  - 无答案问题（`relevant` 为空）不参与可回答问题的平均值，调用方应单独统计。
- `evaluate_qa(ctx, qa_set) -> dict`
  - `qa_set` 字段：`question`、`expected_contexts`、`retrieved`、`retrieved_texts`、`answer`、可选 `k`/`grades`/`judge`。
  - 检索指标在 `retrieval`；答案指标在 `answer`。
  - `faithfulness_token_overlap` 只是词面重合启发式，不是语义忠实度证明。
  - `answer_relevance` 只有在 `judge.status == "ok"` 时才有分数；评审失败保持 `None`，不会用答案长度补分。
- `llm_as_judge(ctx, provider, question, answer, context) -> dict`
  - 成功：`{"status":"ok","reason":"","score":1..10}`。
  - 失败：`{"status":"unavailable","reason":...,"score":None}`；异常原因只记录类型名。
- `evaluate_agent(ctx, trajectory) -> dict`
  - 返回工具正确率、任务成功率和平均延迟。
