# RAG 面试实验记录（Issue #39）

本文记录 2026-11-10 实际运行的检索、切块、位置效应、图检索、框架 PoC、Agent 演示和模型错误回归。脚本与输入在 `experiments/`，原始结果在 `experiments/results/`。

先说明边界：这些结果是公开 CMRC2018 演示语料上的离线实验，不是生产流量、真实用户或真实模型生成质量评测。`hash` 只用于功能测试；Mock 只证明检索和链路；真实 OpenRouter 密钥在 2026-11-10 返回 401 expired，2026-11-11 轮换后完成了一次真实检索问答（记录见 `experiments/results/real-demo-2026-11-11.json`），但仍没有按问题集做系统评测，因此没有真实自然语言答案质量结论。

## 1. 环境与固定条件

| 项 | 本次取值 |
| --- | --- |
| 运行环境 | 服务器 Docker 容器 `ai-rag-platform:ci-34`，Python 3.11 |
| 仓库挂载 | `/opt/agent`（读写，测试需要写临时状态） |
| 模型缓存 | Docker 卷 `ai-rag_model-cache` → `/models`，`FASTEMBED_CACHE_PATH=/models` |
| Embedding | FastEmbed 0.9.0 + `BAAI/bge-small-zh-v1.5`，512 维 |
| 语料 | `data/kb/cmrc2018-demo/knowledge-documents`，24 篇 Markdown |
| 问题集 | `experiments/qa_set.json`，60 题 |
| 检索截断 | `top_k=5`（图实验 `top_k=10`） |
| 切块基线 | 字符切块 500 字符、50 重叠 |
| 生成模型 | 未取得可用真实模型；演示使用 MockProvider |

问题集分布：40 单跳、8 跨段、4 多跳、4 无答案、4 权限边界。`dev`/`test` 按文档划分，不是按题随机划分：

- test：15 题，文档 001、005、006、012、020；
- dev：45 题，其余文档；
- 跨文档多跳题只落在同一侧，避免同一文档同时出现在两个 split；
- `no_answer` 题在语料中没有支持证据；`permission` 题用 `restricted-kb`（仅 008、017、024）检查越权文档是否被检索到。

问题集由 AI 辅助从原文摘录并逐条核对 `evidence` 子串，不是独立人工标注。这个限制必须和指标一起报告。

## 2. 检索策略对照

命令：

```sh
python experiments/run_retrieval.py --backend fastembed --top-k 5 \
  --output experiments/results/retrieval-fastembed.json
```

结果（52 道可回答题；4 道无答案和 4 道权限题不并入可回答题均值）：

| 策略 | Recall@5 | Precision@5 | MRR@5 | nDCG@5 | 证据覆盖 | 平均延迟 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| vector | 0.9808 | 0.4727 | 0.9808 | 0.9808 | 0.9647 | 10.368 ms |
| keyword（当前词面重合） | 1.0000 | 0.5096 | 1.0000 | 0.9985 | 0.9776 | 1.362 ms |
| hybrid（当前加权 RRF） | 1.0000 | 0.4519 | 0.9872 | 0.9904 | 0.9776 | 11.888 ms |
| bm25 | 1.0000 | 0.5208 | 1.0000 | 1.0000 | 0.9776 | 10.283 ms |
| bm25_hybrid | 1.0000 | 0.4615 | 0.9872 | 0.9904 | 0.9679 | 20.573 ms |
| rerank（词面重排） | 0.9808 | 0.4631 | 0.9808 | 0.9808 | 0.9679 | 10.774 ms |

权限题：所有策略的 `questions_with_forbidden_hits` 均为 0，说明本次 `restricted-kb` 范围内没有把 008/017/024 之外的文档返回。

解释：

- 这套题很多来自原文的精确术语、人名和标题，词面检索天然占优；不能据此说 BM25 在所有 RAG 场景都优于向量。
- BM25 是本次新增的真实 BM25 实现，不是把旧词面重合改名；BM25+向量融合没有超过单独 BM25，说明在这批题和候选预算下融合收益有限。
- `rerank` 只是按词面重合重排已召回候选，不是 Cross-encoder，不能补回候选集里没有的证据。
- 延迟是单进程内存检索的观测值，不是生产 p95，也没有并发压测。

## 3. 切块对照

命令：

```sh
python experiments/run_chunking.py --backend fastembed --top-k 5 \
  --output experiments/results/chunking-fastembed.json
```

| 配置 | 块数 | 平均字符 | 构建耗时 | 峰值 RSS | 证据完整率 | vector R@5 | hybrid R@5 | BM25+vector R@5 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| char-500-50 | 86 | 290.9 | 18.059 s | 314.7 MB | 1.0000 | 0.9808 | 1.0000 | 1.0000 |
| char-300-30 | 120 | 210.6 | 12.374 s | 315.0 MB | 1.0000 | 0.9808 | 0.9808 | 1.0000 |
| token-256-32 | 118 | 218.8 | 12.964 s | 315.8 MB | 1.0000 | 0.9808 | 1.0000 | 1.0000 |
| token-512-64 | 72 | 348.2 | 14.155 s | 316.1 MB | 1.0000 | 0.9808 | 1.0000 | 1.0000 |
| structural-256-32 | 118 | 219.2 | 12.498 s | 316.1 MB | 1.0000 | 0.9808 | 1.0000 | 1.0000 |
| structural-512-64 | 72 | 348.8 | 14.096 s | 316.1 MB | 1.0000 | 0.9808 | 1.0000 | 1.0000 |

说明：

- 当前生产默认 `chunk(size=500, overlap=50)` 的单位是**字符**，不是 token。`token-*` 和 `structural-*` 是本次新增的实验接口，没有替换生产默认值。
- `token` 使用正则近似切分：拉丁词按词、中文按单字计数，不等同于模型 tokenizer。`structural` 先按标题/段落边界切，再在段落过长时回退到 token 切块。
- “证据完整率”指每道题的 evidence 子串至少完整出现在一个块中；1.0 等价于本次样本的截断率为 0。它不检查生成上下文是否被截断，也不检查证据跨块后的语义完整性。
- 这批语料每篇只有两个段落：一个 3–11 token 的标题和一个 527–884 token 的正文。正文超过 256/512 预算后回退到 `chunk_tokens`，标题单独成块，因此 `structural-*` 与 `token-*` 的块数完全相同（118/72），本次没有真正测到多段打包；结构性切块的价值仍需用多段语料重测。
- 在这批 24 篇文档、60 道题上，token/structural 没有带来可观测的检索提升；字符 500/50 仍是合理基线。这个结论不外推到其他语料。
- 构建耗时和 RSS 来自单次运行，受模型缓存、容器冷热和并发影响；不能当作容量承诺。

## 4. Lost in the Middle 控制变量实验

命令：

```sh
python experiments/run_lost_in_middle.py --provider mock \
  --output experiments/results/lost-in-the-middle-mock.json
```

构造方式：同一问题、同一证据、同一组干扰片段，只把证据放在 `[1]`（开头）、`[3]`（中间）或 `[5]`（结尾）。共 8 个问题 × 3 个位置 = 24 条记录。

实际结果：所有记录都是 `provider=mock`、`status=mock_not_evidence`、`quality_conclusion=unavailable`；`exact_contains_expected=false`、`cites_evidence_number=false`。这不是位置效应结论，只证明上下文构造和脚本可运行。

未完成：真实模型位置效应实验。2026-11-11 轮换后的 OpenRouter 密钥已能做单次真实问答，但还没有按本实验的 8 个问题 × 3 个位置跑真实模型，因此不能编造正确率或引用支持率；也没有验证重排、去重或压缩是否缓解位置效应。

## 5. 图检索小实验

命令：

```sh
python experiments/run_graph.py --backend fastembed --top-k 10 \
  --output experiments/results/graph-fastembed.json
```

数据是 `experiments/graph_data.json` 中的合成服务依赖图（6 个服务、8 个问题），图只建在内存里，没有引入 Neo4j 或第二套数据库。

| 方法 | 平均实体召回 | 平均延迟 |
| --- | ---: | ---: |
| 向量检索 | 1.0000 | 10.232 ms |
| 内存 BFS 图路径 | 1.0000 | 0.058 ms |

两种方法在这 8 个问题上都找回了答案实体。图路径的优势是关系结构清晰、可解释；代价是实体消歧、错误关系、构图和更新成本。本次没有生产图数据库，也没有把 GraphRAG 的实体抽取/社区摘要写成已实现。

## 6. 框架最小 PoC

命令：

```sh
python experiments/run_framework_poc.py --backend fastembed --limit 20 \
  --output experiments/results/framework-poc.json
```

使用 `llama-index-core==0.12.52`，把项目的 `make_embed` 包装成 `BaseEmbedding`，对同一批 20 道题做最小索引和检索。

| 方法 | Recall@5 | MRR@5 | 平均延迟 |
| --- | ---: | ---: | ---: |
| LlamaIndex PoC | 0.9500 | 0.9500 | 11.792 ms |
| 项目内存基线 | 0.9500 | 0.9500 | 9.963 ms |

PoC 脚本 184 行，峰值 RSS 391.8 MB，运行 29.749 秒（含建索引）。结论：在这个最小场景里，LlamaIndex 没有带来质量提升，延迟略高，依赖和内存成本增加；因此不迁移生产。RAGFlow、Haystack、LangChain/LangGraph、Ragas 只做了资料调研，没有运行，不能写成“实践过”。

## 7. Agent 多跳、重复查询与无证据停止

命令：

```sh
python experiments/run_mock_agent_demo.py --backend fastembed \
  --output experiments/results/mock-agent-demo.json
```

实际结果：问题“请查资料，什么是静电感应？”使用真实 BGE 检索，命中 5 个片段；`agent_stop.stop_reason=answered_with_evidence`，`retrieval_calls=1`。生成使用 MockProvider，答案只是 Mock 工具 JSON，不能作为自然语言答案质量证据。

代码行为：

- 已选择知识库但模型直接收尾：最多提醒 `MAX_RETRIEVAL_REMINDERS` 次，仍不检索则返回 `NO_EVIDENCE_ANSWER`，停止原因 `retrieval_required_not_met`；
- 检索结果解析出 `hit_count=0`：返回 `NO_EVIDENCE_ANSWER`，停止原因 `no_evidence`；
- 重复完全相同的 `(tool, arguments)`：不执行，返回重复查询提示并记录 `retrieval_guard(reason=duplicate_query)`；
- 正常有证据：停止原因 `answered_with_evidence`；未选知识库：`answered`；达到轮数上限：`max_tool_rounds`。

预算：调用预算由 `AgentRuntime.max_tool_rounds`（默认 10，不允许小于 10）控制；HTTP 层还有 120 秒单次问答总时限。`AgentRuntime` 自身没有 wall-clock deadline，这是未完成项。普通工具循环不等于 FLARE 或 Self-RAG。

## 8. 真实检索问答演示与错误区分

命令：

```sh
python scripts/demo_rag_evidence.py --base-url http://127.0.0.1:18080 \
  --question "请查资料，什么是静电感应？"
```

脚本先打印检索命中，再打印生成答案和停止原因。2026-11-11 轮换新 OpenRouter key 后，对运行中的 0.9.0 服务复演并保存结果到 `experiments/results/real-demo-2026-11-11.json`：`provider=openrouter`、`model=openrouter/free`、`embedding=fastembed`；检索返回 14 条 `008-静电感应` 等命中，真实模型返回带引用的自然语言答案，HTTP 200，额度计数 `used=3`、`remaining=97`。部署镜像仍是 0.9.0，trace 没有本 PR 新增的 `agent_stop`，`stop_reasons` 为空；因此这次演示证明“真实检索 + 真实生成 + 引用”链路，不证明本 PR 的停止逻辑，也没有做逐句人工核验，不能报准确率。2026-11-10 的 401 expired 记录保留为失败样本。脚本在生成失败时仍会单独列出已有命中，用来区分：

- 没有命中：检索失败，不是生成失败；
- 有命中但模型调用失败：证据存在，生成不可用；
- 有命中且生成成功：仍需人工核对答案是否被证据支持。

`experiments/results/mock-agent-demo.json` 是同一问题的进程内 Mock 版本，保留真实检索和停止原因，明确标注 Mock 限制。

## 9. 模型错误回归

命令：

```sh
python scripts/check_llm_errors.py \
  --output experiments/results/llm-error-regression.json
```

用 `httpx.MockTransport` 模拟上游响应，验证错误映射：

| 上游状态 | 项目错误码 | HTTP 状态 |
| --- | --- | --- |
| 401/403 | `model_auth_failed` | 502 |
| 402 | `model_quota_exhausted` | 502 |
| 404 | `model_not_found` | 502 |
| 400/422 | `model_request_rejected` | 502 |
| 429 | `model_rate_limited` | 429 |
| 其他失败 | `model_unavailable` | 503 |
| 超时 | `model_timeout` | 504 |

真实 OpenRouter 检查（`https://openrouter.ai/api/v1/key`）在 2026-11-10 对旧 key 返回 HTTP 401 `model_auth_failed`（“API key expired.”），记录中已脱敏；2026-11-11 轮换后返回 HTTP 200，真实问答成功。密钥存在、模型列表可见或一次连通性检查仍不能代替系统质量评测；本次只记录一次真实演示，没有准确率结论。

## 10. 未完成与不采用

| 事项 | 状态 | 原因 / 下一步 |
| --- | --- | --- |
| 第二个中文 embedding 模型对照 | 未完成 | 服务器模型下载和内存受限；不用 hash 冒充。需要可用模型和固定缓存后重跑。 |
| 真实模型生成质量 / Lost in the Middle 质量结论 | 未完成 | 2026-11-11 新 key 已能完成一次真实检索问答，但还没有按同一问题集做系统评测和人工抽查；不能把一次演示写成准确率。 |
| Cross-encoder reranker | 未实现 | 当前 `rerank` 只是词面重排；引入 Cross-encoder 需要额外模型内存和延迟预算。 |
| 生产 BM25/融合切换 | 不采用 | 本次 BM25 在精确术语题上占优，但样本小且词面偏差明显；保持现有可切换实验接口，不替换默认检索。 |
| 图数据库 / GraphRAG 生产化 | 不采用 | 合成数据只验证小实验；生产需要实体抽取、消歧、更新和权限传播。 |
| LlamaIndex 生产迁移 | 不采用 | 最小 PoC 无质量提升、延迟略高、依赖和内存增加。 |
| ANN / 倒排索引 | 未实现 | 当前 24 篇文档用 SQLite JSON 向量 + NumPy 精确排序足够；规模阈值需要单独压测，不能凭感觉写数字。 |
| Agent wall-clock deadline | 未实现 | 当前只有轮数上限和 HTTP 120 秒总时限；进程内循环本身没有截止时间。 |
| 后台任务跨重启恢复 | 未实现 | 0.9.1 后台导入仍是进程内任务；重启后的行为按现有文档和测试记录。 |

## 11. 复现与清理

所有脚本都接受 `--output`，结果写到 `experiments/results/`。测试和实验使用的临时状态放在 `/tmp` 或容器临时目录，运行后清理；仓库不保存模型缓存、密钥、用户原文、会话令牌或一次性本地路径。

完整命令和每个脚本的输入输出见 [`experiments/README.md`](../experiments/README.md)。指标口径见 `modules-src/evaluation/INTERFACE.md` 与 `API_SCHEMA.json`。

上传、删除、更新可见性、权限隔离、长任务和重启的现有入口是应用测试：

```sh
# 需要已编译工件；Jenkins 在 compiled 镜像中执行
python scripts/run_tests.py --mode binary --group app

# 单独复跑权限和资源/长任务相关用例
python -m pytest apps/ragnotebook/tests/test_notebook_permissions.py \
  apps/ragnotebook/tests/test_resource_management.py -q
```

本轮在 `ai-rag-platform:ci-34` 中运行的是源码模块、脚本和接口规范测试；没有重新编译 Linux 二进制，也没有重跑应用测试。因此这些入口只说明“怎么复演”，不把本轮未执行的用例写成通过。
