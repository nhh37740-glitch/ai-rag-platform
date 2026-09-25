# Module Interfaces（模块接口契约）

所有模块实现 `modules-src/<module>/`（独立可安装包，含 `pyproject.toml` + `src/` + `tests/` + `README.md`），对外只暴露下面这些接口。集成侧 `apps/agent-server` 只 import 这些接口直调。除 `core_contracts` 外，任何模块不得直接依赖另一个模块的实现，只能通过 `contracts.core_contracts` 共享类型。

约定：所有公共函数**必须接收 `RequestContext`**；除 `generate/stream` 外的同步方法如需阻塞 IO，由调用方 `asyncio.to_thread` 包裹。返回类型来自 `core_contracts`。

## llm_gateway
```python
class LLMProvider(Protocol):
    async def generate(self, ctx, messages: list[ChatMessage], tools: list[ToolDef] | None = None
                       ) -> tuple[str, list[ToolCall]]: ...        # (answer, tool_calls)
    async def stream(self, ctx, messages: list[ChatMessage], tools: list[ToolDef] | None = None): ...

class DeepSeekProvider:  # httpx，读 DEEPSEEK_API_KEY / DEEPSEEK_BASE_URL / DEEPSEEK_MODEL
    def __init__(self, api_key: str, base_url: str = "https://api.deepseek.com", model: str = "deepseek-chat"): ...

class MockProvider:  # 离线：按预置答案/工具调用规则返回，用于演示与测试
    def __init__(self, scenario: str = "qa"): ...
```

## rag_core
```python
class VectorStore(Protocol):
    def add(self, source_id: str, chunks: list[str], embeddings) -> None: ...
    def search(self, embedding, top_k: int = 5, scopes: list[str] | None = None) -> list[tuple[str, str, float]]: ...
    def list_documents(self, scopes: list[str] | None = None) -> list[tuple[str, int]]: ...   # (source_id, chunk_count)
    def document_chunks(self, source_id: str) -> list[str]: ...                               # 该文档全部块，按写入顺序

class InMemoryVectorStore:  # numpy 余弦相似度，离线
class SqliteVectorStore:    # SQLite 持久化文本与向量，搜索接口与内存实现一致

class RagClient:
    def __init__(self, store: VectorStore, embed_fn=embed, top_k: int = 5): ...
    def retrieve(self, ctx, query: str, scope: str | list[str] | None = "kb",
                 top_k: int | None = None) -> RetrievalResult: ...

def embed(texts: list[str]) -> list[list[float]]: ...          # 默认 FastEmbed + BAAI/bge-small-zh-v1.5；失败直接报错
def retrieve(ctx, query: str, store: VectorStore,
             scope: str | list[str] | None = "kb", top_k: int = 5) -> RetrievalResult: ...

# 检索原语：供 rag_tools 组装成 LLM 工具
def keyword_search(ctx, query: str, store: VectorStore,
                   scope: str | list[str] | None = "kb", top_k: int = 5) -> RetrievalResult: ...
    # 纯词面打分，不加载向量模型
def hybrid_search(ctx, query: str, store: VectorStore, scope: str | list[str] | None = "kb",
                  top_k: int = 5, alpha: float = 0.5) -> RetrievalResult: ...
    # 向量与词面排序的 RRF 融合；正文含罕见词时能纠正纯向量排序
def list_documents(ctx, store: VectorStore, scope: str | list[str] | None = "kb") -> list[dict]: ...
    # [{source_id, title, knowledge_base_id, chunk_count}]
def document_info(ctx, store: VectorStore, source_id: str) -> dict: ...
    # {source_id, title, knowledge_base_id, chunk_count}；未知 id 时 chunk_count 为 0
def read_document(ctx, store: VectorStore, source_id: str,
                  max_chunks: int = DEFAULT_READ_CHUNKS, offset: int = 0) -> RetrievalResult: ...
    # 分页读取，绝不允许一次读完整篇：默认 DEFAULT_READ_CHUNKS=20 块，上限 MAX_READ_CHUNKS=100。
    # 每个 Citation.metadata 含 knowledge_base_id、chunk_index（1 起）、total_chunks。
```

`read_document` 必须分页：调用方无法用一次调用取回整篇文档，只能通过递进 `offset` 续读。这样大文档不会一次撑爆上下文。

`RAG_EMBED` 默认为 `fastembed`；只有显式设置 `RAG_EMBED=hash` 时才允许使用不经模型的离线 hash 向量。未安装 FastEmbed、模型无法加载或配置了未知后端时必须报错，不得静默降级。

## rag_tools
```python
class RagTools:
    def __init__(self, store: VectorStore, tracing: TraceStore, top_k: int = 5): ...
    def tool_definitions(self) -> list[ToolDef]: ...
    def search(self, ctx, query: str, knowledge_base_ids: list[str], top_k: int | None = None) -> str: ...
    def hybrid_search(self, ctx, query: str, knowledge_base_ids: list[str], top_k: int | None = None) -> str: ...
    def keyword_search(self, ctx, query: str, knowledge_base_ids: list[str], top_k: int | None = None) -> str: ...
    def list_documents(self, ctx, knowledge_base_ids: list[str]) -> str: ...
    def read_document(self, ctx, source_id: str, knowledge_base_ids: list[str],
                      offset: int = 0, max_chunks: int | None = None) -> str: ...
```

`read_knowledge_document` 的返回值必须包含 `offset`、`returned_chunks`、`total_chunks`、`truncated` 与 `next_offset`（读到底时为 `null`）。工具参数为 `source_id`（必填）、`offset`（≥0）、`max_chunks`（1–100，默认 20）。工具描述必须写明它默认只返回前若干块，并要求模型在被截断时用 `next_offset` 续读，而不是假设一次拿到全文。

`RagTools` 是 RAG 工具模块（原 `rag-skill`，0.2.0 起改名）：向 LLM 公布五个工具
`search_knowledge_base`、`hybrid_search_knowledge_base`、`keyword_search_knowledge_base`、
`list_knowledge_documents`、`read_knowledge_document`，每个方法返回 JSON 字符串并记录一个
`rag` span（`meta` 含 `tool`/`query`/`knowledge_base_ids`/`hit_count`/`hits`）。
知识库范围必须由当前请求上下文注入，不允许 LLM 自行扩大；`read_document` 对范围外的
`source_id` 直接报错。提示词层面的检索策略位于 `skills/rag-retrieval/SKILL.md`。

## memory
```python
class MemoryStore:
    def get(self, ctx, namespace: str, key: str) -> MemoryEntry | None: ...
    def write(self, ctx, namespace: str, key: str, content: str, importance: float = 0.0) -> MemoryEntry: ...
    def search(self, ctx, namespace: str, query: str, top_k: int = 5) -> list[MemoryEntry]: ...
    def forget(self, ctx, namespace: str, key: str) -> None: ...

def make_memory(db_path: str) -> MemoryStore: ...   # session + user 两个 namespace 共用一个 SQLite
```

## tool_runtime
```python
def tool(name: str, description: str, parameters: dict,
         context_aware: bool = False) -> Callable: ...   # 装饰器，注册进默认 registry
class ToolRegistry:
    def register(self, t: ToolDef, fn, context_aware: bool = False): ...
    def list(self, ctx) -> list[ToolDef]: ...
    def execute(self, ctx, call: ToolCall, runtime_context: dict | None = None) -> str: ...
```

## mcp_gateway
```python
class McpServerClient:   # 与外部 MCP server 交互；v1 提供 MockClient
    async def connect(self, name: str) -> None: ...
    async def list_tools(self) -> list[ToolDef]: ...
    async def call_tool(self, name: str, arguments: dict) -> str: ...

def normalize_to_tool(mcp_tool: dict) -> ToolDef: ...   # 统一成 ToolDef
```

## mcp_servers（独立进程/API，mock）
```python
# 独立可执行文件 mcp-servers(.exe)，暴露真实 MCP JSON-RPC（stdio）+ 可选 HTTP。
# v1 连接器为本地 mock（Git / Issue / 工单），接口与真实连接器一致。
# --stdio                 走 MCP JSON-RPC over stdio
# --http :<port>          可选 HTTP 端点
def run_stdio() -> None: ...     # 读 JSON-RPC，分发到 git/issue/ticket handlers
def tools_manifest() -> list[ToolDef]: ...   # 与 mcp_gateway.normalize_to_tool 对齐
```

## skill_runtime
```python
class SkillRegistry:
    def list(self, ctx) -> list[SkillDef]: ...
    def load(self, ctx, name: str) -> SkillDef: ...        # 惰性展开 SKILL.md 指令
    def load_dir(self, path: str) -> None: ...             # 扫描 skills/<name>/SKILL.md
    def render(self, ctx, query: str) -> str: ...          # 选择相关 Skill 并返回完整指令
```

## agent_runtime
```python
class AgentRuntime:
    def __init__(self, provider, memory, tools, skills, tracing, max_tool_rounds: int = 10): ...
    async def run(self, ctx, user_input: str, knowledge_base_ids: list[str] | None = None) -> str: ...
```

## observability
```python
class Span:   # async context manager，记录 trace_id/span/耗时
    def __init__(self, ctx, name: str): ...
class TraceStore:
    def record(self, span: SpanEvent) -> None: ...
    def get(self, trace_id: str) -> list[SpanEvent]: ...
```

`rag` span 的 `meta` 必须包含 `query`、`knowledge_base_ids`、`hit_count` 和按排名排列的 `hits`；每个命中项记录 `rank`、`source_id`、`title`、`score` 与截断后的 `text_preview`。

`retrieval_guard` span 在“已选择知识库、但本轮没有执行任何检索，模型却想直接收尾”时记录，`meta` 含 `attempt`（第几次提醒）与 `knowledge_base_ids`。`agent_runtime` 会对这种回答打回重来，最多 `MAX_RETRIEVAL_REMINDERS` 次。

## evaluation（独立进程/API）
```python
def evaluate_qa(ctx, qa_set: dict) -> dict: ...   # Retrieval Recall/Precision, Faithfulness, Answer Relevance
def evaluate_agent(ctx, trajectory: list) -> dict: ...
```

## ingestion（独立进程/API）
```python
def parse(path: str) -> list[str]: ...        # PDF/DOCX/MD/TXT → 文本块
def to_markdown(path: str, title: str = "") -> str: ...  # 统一转换成带标题的 Markdown
def chunk(texts: list[str], size: int = 500, overlap: int = 50) -> list[str]: ...
def build_index(ctx, docs_dir: str, store: VectorStore) -> int: ...   # parse→chunk→embed→索引

# 同仓库另产 ingestion-worker(.exe)：包装上述函数，仅暴露 POST /ingest
#   POST /ingest  body: {"docs_dir": "...", "scope": "kb"}  ->  {"indexed": <int>}
```

## 集成约束
- 依赖上限：`core_contracts` 外的模块只允许用标准库、`httpx`、`numpy`、`sklearn`、`pypdf`；不得引入未声明的第三方库。
- 测试用标准库 `unittest`（无 pytest），放在各模块 `tests/`。
- 不得改动 `contracts/`、其他模块或 `docs/PLAN.md`；只写自己模块目录。

## 模块生命周期（subagent 发布流程）
每个模块是 `modules-src/<module>` 下的独立 git 仓库。发布一次 = 一次提交：
1. 实现 `src/<package>/` 并让 `tests/`（unittest，mock 外部依赖）全绿。
2. 编译：进程内模块用 mypyc（默认）/Cython（回退）产出 `.pyd`；`mcp-servers`、`ingestion-worker` 用 Nuitka 产出 `.exe`。
3. 在仓库内更新 `README.md`、`INTERFACE.md`、`API_SCHEMA.json`、`CHANGELOG.md`、`VERSION`（遵循 semver）。
4. 计算二进制 `checksum.sha256`，把 `INTERFACE.md`/`API_SCHEMA.json`/`VERSION`/`CHANGELOG.md`/`test_contract.py`/`checksum.sha256`/编译产物 发布到 `artifacts/<module>/<version>/`。
5. 更新根 `registry.json` 中该模块的 `version`/`checksum`/`status="published"`。
6. 集成侧运行 `python contracts/test_contract.py` 校验，通过后视为发布成功。
