# 评测基线

| 问题 | Recall | Precision | Faithfulness | AnswerRel | Judge |
|---|---|---|---|---|---|
| XX API 如何认证？ | 1.0 | 0.5 | 0.3 | 1.0 | 3 |
| 连接超时怎么排查？ | 1.0 | 0.333 | 0.0 | 1.0 | 3 |
| 系统是怎么分层的（记忆、工具、技能）？ | 0.0 | 0.0 | 0.0 | 1.0 | 10 |

**汇总**：平均 Recall 0.667，Faithfulness 0.1，AnswerRel 1.0，LLM-Judge 5.33。

> 说明：当前为 Mock/规则基线，接入 DeepSeek 与真实评测集后可复现更严格指标。