# RAG 面试实验

本目录保存 Issue #39 的可复跑实验脚本、输入数据和结果文件。实验只使用现有公开 CMRC2018 演示语料，不连接生产数据库，不修改四 facade、单 SQLite、六表结构或二进制运行边界。

先读 [docs/EXPERIMENTS.md](../docs/EXPERIMENTS.md)：那里记录实验方法、实际结果、失败记录和未完成项。本文件只说明每个脚本做什么、输入输出是什么。

## 数据

| 文件 | 内容 |
| --- | --- |
| `qa_set.json` | 60 道题：40 单跳、8 跨段、4 多跳、4 无答案、4 权限边界。`dev`/`test` 按文档划分，test 文档为 001、005、006、012、020，其余文档在 dev。 |
| `graph_data.json` | 合成的服务依赖图，6 个服务、8 个问题，仅用于内存图实验。 |
| `results/` | 本次实际运行输出；文件内记录 backend、top_k、参数和限制说明。 |

`qa_set.json` 由 AI 辅助从原文摘录并逐条核对 `evidence` 子串，不是独立人工标注。`no_answer` 题在语料中没有支持证据；`permission` 题用 `restricted-kb`（仅 008、017、024）验证越权文档不可见。

## 脚本

| 脚本 | 作用 | 主要输出 |
| --- | --- | --- |
| `run_retrieval.py` | 固定问题集和 `top_k`，比较 vector、keyword、hybrid、BM25、BM25+vector、lexical rerank。 | 每题排名指标、证据覆盖、禁止命中、延迟和汇总。 |
| `run_chunking.py` | 比较字符、token、结构切块的块数、构建耗时、内存、证据完整率和检索效果。 | 每种切块配置的汇总与逐题记录。 |
| `run_lost_in_middle.py` | 固定问题、证据和干扰片段，只改变证据在上下文中的位置。 | start/middle/end 三组记录；Mock 模式明确标记 `mock_not_evidence`。 |
| `run_graph.py` | 在同一合成数据上比较向量检索和内存 BFS 图路径。 | 实体召回、路径和延迟。 |
| `run_framework_poc.py` | 用 LlamaIndex core 对同一语料做最小索引和检索，与项目内存基线比较。 | 框架/基线 Recall、MRR、延迟、RSS；未安装时记录 `unavailable`。 |
| `run_mock_agent_demo.py` | 进程内跑通 AgentRuntime + RagTools + 真实 BGE 检索，生成使用 MockProvider。 | 检索命中、停止原因、Mock 限制说明。 |
| `../scripts/demo_rag_evidence.py` | 调用运行中的服务，分别打印检索命中和生成答案。 | 问题、命中文档、证据片段、答案、trace、额度。 |
| `../scripts/check_llm_errors.py` | 用假 HTTP 响应验证错误映射；有 `OPENROUTER_API_KEY` 时做一次真实鉴权检查。 | 脱敏的错误码、HTTP 状态、延迟。 |

## 运行

以下命令假定当前目录是仓库根目录，且依赖和模型缓存已准备好。不要提交模型缓存、密钥、用户原文或一次性报告。

```sh
python experiments/run_retrieval.py --backend fastembed --top-k 5 \
  --output experiments/results/retrieval-fastembed.json

python experiments/run_chunking.py --backend fastembed --top-k 5 \
  --output experiments/results/chunking-fastembed.json

python experiments/run_lost_in_middle.py --provider mock \
  --output experiments/results/lost-in-the-middle-mock.json

python experiments/run_graph.py --backend fastembed --top-k 10 \
  --output experiments/results/graph-fastembed.json

python experiments/run_framework_poc.py --backend fastembed --limit 20 \
  --output experiments/results/framework-poc.json

python experiments/run_mock_agent_demo.py --backend fastembed \
  --output experiments/results/mock-agent-demo.json

python scripts/check_llm_errors.py \
  --output experiments/results/llm-error-regression.json
```

本次实际运行在服务器 Docker 容器 `ai-rag-platform:ci-34`（Python 3.11）中完成，仓库挂载到 `/opt/agent`，FastEmbed 缓存卷挂载到 `/models`。本机没有 Python 运行时，因此没有用本机结果冒充服务器结果。

服务演示需要先启动服务：

```sh
python scripts/demo_rag_evidence.py --base-url http://127.0.0.1:18080 \
  --question "请查资料，什么是静电感应？"
```

`demo_rag_evidence.py` 只读调用公开 HTTP API，不读取密钥。若生成失败，它仍会单独列出检索命中，用来区分“没找到证据”和“找到证据但模型调用失败”。

## 结果边界

- `hash` 只用于离线功能测试，不能作为语义模型质量结果。
- Mock 生成只证明检索、引用字段和 trace 链路，不代表自然语言答案质量。
- `rerank` 是词面重排，不是 Cross-encoder。
- 图实验使用合成数据和内存图，不代表生产图数据库选型。
- LlamaIndex 只跑了最小 PoC，没有迁移生产。
- 真实 OpenRouter 检查只记录脱敏错误；本次密钥返回 401 expired，没有真实模型质量结论。
