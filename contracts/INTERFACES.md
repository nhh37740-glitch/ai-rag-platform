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
    def search(self, embedding, top_k: int = 5, scopes: list[str] | None = None) -> list[tuple[str, float]]: ...

class InMemoryVectorStore:  # numpy 余弦相似度，离线
class SqliteVectorStore:    # 可选，SQLite + numpy

def embed(texts: list[str]) -> list[list[float]]: ...          # BGE 适配层；离线用 hash/均值兜底
def retrieve(ctx, query: str, scope: str | list[str] | None = "kb", top_k: int = 5) -> RetrievalResult: ...
```

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
def tool(name: str, description: str, parameters: dict) -> Callable: ...   # 装饰器，注册进默认 registry
class ToolRegistry:
    def register(self, t: ToolDef, fn): ...
    def list(self, ctx) -> list[ToolDef]: ...
    def execute(self, ctx, call: ToolCall) -> str: ...
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
```

## agent_runtime
```python
class AgentRuntime:
    def __init__(self, provider, rag, memory, tools, skills, tracing): ...
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
