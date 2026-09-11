# rag-skill

面向 Agent 的知识库检索工具模块。它把 `rag_core.retrieve` 封装为
`search_knowledge_base`，允许模型生成或改写查询词，但知识库范围只能由当前请求注入。

## 接口

```python
from rag_skill import RagSkill

skill = RagSkill(store=vector_store, tracing=trace_store, top_k=5)
tool = skill.tool_definition()
result_json = skill.execute(ctx, "奥卡姆剃刀", ["cmrc2018-demo"])
```

`result_json` 包含查询、命中数量和带来源的引用。每次执行都会记录一个 `rag` span；
模型不能通过工具参数查看或修改 `knowledge_base_ids`。

`top_k` 的有效范围为 1–20。
