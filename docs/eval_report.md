# 评测基线

| 问题 | Recall | Precision | Faithfulness | AnswerRel | Judge |
|---|---|---|---|---|---|
| XX API 如何认证？ | 1.0 | 0.5 | 0.333 | 1.0 | 8 |
| 连接超时怎么排查？ | 1.0 | 0.5 | 0.219 | 1.0 | 7 |
| 系统是怎么分层的（记忆、工具、技能）？ | 1.0 | 0.5 | 0.192 | 1.0 | 8 |

**汇总**：平均 Recall 1.0，Faithfulness 0.248，AnswerRel 1.0，LLM-Judge 7.67。

> 说明：当前为 Mock/规则基线，接入 DeepSeek 与真实评测集后可复现更严格指标。