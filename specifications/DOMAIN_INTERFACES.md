# 业务模块接口规范（0.2.0）

唯一共享类型和 Protocol 位于 `core_specifications`。下列签名同时登记在 `API_SCHEMA.json`，实现不得自行增删必需参数。业务方法的第一个参数均为 `ctx: RequestContext`（不计 self）。

## 数据库：data-facade / data_facade

```python
class DataService:
    def __init__(self, state_dir: str, memory_db_path: str | None = None,
                 vector_db_path: str | None = None): ...
    def initialize(self, ctx: RequestContext) -> None: ...
    def memory_store(self, ctx: RequestContext) -> MemoryStorePort: ...
    def vector_store(self, ctx: RequestContext) -> VectorStore: ...
    def state_db(self, ctx: RequestContext) -> StateStorePort: ...
    def close(self, ctx: RequestContext) -> None: ...
```

目录可不存在，首次创建并初始化。默认 memory.sqlite、vectors.sqlite、state.sqlite；覆盖路径允许 :memory:。同实例多次取 store 返回同一对象，初始化幂等。关闭幂等，关闭后取 store 或 initialize 抛 RuntimeError。关闭后此前拿到的 store 也不可再访问；关闭释放 SQLite 连接，Windows 临时目录可以清理。

SQLite 向量实现位于 storage，数据库域不得 import rag_core。VectorStore.add 对一个 source_id 原子替换全部块，避免重启/重复入库膨胀；先验证块数与向量数量、非空一致维度、有限数值再提交。scope=None 为全部，scope=[] 为无文档。state_db 是按用户隔离的 JSON 键值门面，不暴露裸连接，get 缺键返回 None，set/delete 持久化。已有 vectors 表和 memory 表保持兼容。

## RAG：rag-facade / rag_facade

```python
class RagService:
    def __init__(self, store: VectorStore, tracing: TraceStorePort, top_k: int = 5): ...
    def tool_definitions(self, ctx: RequestContext) -> list[ToolDef]: ...
    def execute_tool(self, ctx: RequestContext, call: ToolCall, knowledge_base_ids: list[str]) -> str: ...
    def search(self, ctx: RequestContext, query: str, knowledge_base_ids: list[str],
               top_k: int | None = None, mode: str = "vector") -> RetrievalResult: ...
    def list_documents(self, ctx: RequestContext, knowledge_base_ids: list[str]) -> list[dict]: ...
    def read_document(self, ctx: RequestContext, source_id: str, knowledge_base_ids: list[str],
                      offset: int = 0, max_chunks: int | None = None) -> RetrievalResult: ...
    def parse_document(self, ctx: RequestContext, path: str, title: str = "") -> str: ...
    def split_text(self, ctx: RequestContext, text: str) -> list[str]: ...
    def embed_texts(self, ctx: RequestContext, texts: list[str]) -> list[list[float]]: ...
    def ingest(self, ctx: RequestContext, path: str, knowledge_base_id: str,
               source_id: str = "") -> IngestResult: ...
    def ingest_markdown(self, ctx: RequestContext, markdown: str, source_id: str) -> IngestResult: ...
```

只接收注入的 VectorStore，不负责创建连接。search mode 仅 vector/hybrid/keyword；top_k 整数 1..20（bool 非整数），空查询 ValueError。知识库范围必须显式给出，[] 返回空结果；范围外 read 抛 ValueError，未知范围返回空结果。read 默认最多20块，上限100；offset 非负整数（bool 无效）。分页元数据沿用 rag-core/RagTools。source_id 必须为 `<knowledge_base_id>/<document_id>`，拒绝空值、路径穿越或与指定知识库不匹配。ingest 转 Markdown 并分块/向量化，返回共享 IngestResult；空文本不能入库。

execute_tool 复用 rag-tools 的五个只读工具和 JSON 返回格式，参数中的 knowledge_base_ids/ctx/runtime_context 不得覆盖注入范围；未知工具 ValueError。每次执行保留含实际 tool/scope/source 的 rag span。typed search/list/read 也须记录 rag span；目录工具沿用现有 hit_count 计数，搜索和读取记录实际 hits。parse_document 复用 ingestion，支持 md/txt/docx/pdf，未知格式 ValueError。不得 import 数据库叶子或其他中间包。

## AGENT：agent-facade / agent_facade

```python
def make_provider(api_key: str = "", base_url: str = "https://api.deepseek.com",
                  model: str = "deepseek-chat", scenario: str = "qa") -> LLMProviderPort: ...
class AgentService:
    def __init__(self, data: DataServicePort, rag: RagServicePort, tracing: TraceStorePort,
                 skill_dir: str = "", provider: LLMProviderPort | None = None,
                 max_tool_rounds: int = 10): ...
    async def run(self, ctx: RequestContext, user_input: str,
                  knowledge_base_ids: list[str] | None = None) -> str: ...
    def register_tool(self, ctx: RequestContext, definition: ToolDef,
                      handler: Callable, context_aware: bool = False) -> None: ...
    def tool_definitions(self, ctx: RequestContext) -> list[ToolDef]: ...
    def history(self, ctx: RequestContext) -> list[ChatMessage]: ...
    async def aclose(self, ctx: RequestContext) -> None: ...
```

中间包内部装配 AgentRuntime、ToolRegistry、SkillRegistry；接收接口对象，不 import memory/rag_core/rag_tools/ingestion/storage。装配时自动注册五个 RAG 工具，scope 只取当前 run 的运行上下文，忽略模型伪造的范围。额外工具通过 register_tool 添加；禁止替换五个保留 RAG 名称。history 返回副本，按 user/session 隔离。provider 可注入，默认 Mock；make_provider 非空 key 为 DeepSeek，空 key 为 Mock。aclose 幂等，释放自建资源，不关闭外部注入的 data/rag/provider；关闭后 run/register/history/tool_definitions 抛 RuntimeError。run 拒绝空输入；保持原有 max_tool_rounds>=10 约束。可读 provider 属性用于请求级适配核查。

## 先定义的验收用例

| 编号 | 负责人 | 输入/操作 | 必须断言 |
|---|---|---|---|
| D01 | 数据库 | 临时目录，initialize 两次 | 无错，三个 store 身份稳定 |
| D02 | 数据库 | 写 memory/vector/state，close 后重建 | 内容持久化、用户 state 隔离 |
| D03 | 数据库 | 同 source 重复 add；错误向量 | 原子替换，错误不破坏旧记录 |
| D04 | 数据库 | []、未知 scope 与恶意 SQL 文本 | 无越界结果，参数化 SQL |
| D05 | 数据库 | close 两次，关闭后访问 | 幂等，RuntimeError，临时目录能删除 |
| R01 | RAG | 假 VectorStore 空库、未知 scope、[] | 返回类型正确，无泄露 |
| R02 | RAG | 临时 md/txt/docx 导入后 search/list/read | 同 source，块数一致，正确范围 |
| R03 | RAG | top_k=0/21/True；空 query；非法 mode | 预期 TypeError/ValueError |
| R04 | RAG | 范围外 read、穿越 source、分页 | 拒绝越界，页长/offset/metadata 正确 |
| R05 | RAG | 执行五个工具，伪造 scope | 定义匹配，JSON 格式/trace 保留，范围不被覆盖 |
| A01 | AGENT | 假 DataServicePort/RagServicePort + Mock | 不依赖跨域实现，完成一轮 |
| A02 | AGENT | 选范围运行，模型伪造 knowledge_base_ids | RAG 只收到当前范围，trace 同 ctx |
| A03 | AGENT | 加工具、撞保留名称、加载真实 SKILL.md | 工具执行与技能完整内容可用，保留工具不可替换 |
| A04 | AGENT | 同 user 不同 session 及不同 user | history 隔离、返回副本 |
| A05 | AGENT | aclose 两次后再 run/register | 幂等，不关闭注入依赖，拒绝调用 |
| I01 | 协调 | Agent、RAG、Data facade + 临时持久库 + md | 入库→检索→Agent→引用→trace→重开 |
| I02 | 协调 | 编译后回放模块/接口/最终服务测试 | 来自当前平台 .pyd/.so，不从源码加载 |
| I03 | 协调 | AST 检查应用与域 import | 只准四个业务 facade/公共层；域间不碰具体叶子 |
| I04 | 协调 | CMRC 24 文档/99 问题 | 实际来源范围、回归下限、失败列出 question_id |
| I05 | 协调 | 每次构建固定精选问题，真实 DeepSeek | 非 Mock、实际引用与 rag span；密钥缺失失败 |

源码 tests 放各模块 tests/，使用 unittest，可由 pytest 收集；协调集成测试放 scripts/tests/，二进制与网页测试保留服务目录。所有临时数据用 tempfile，不写基线语料。

## 鉴权业务与运行时边界

管理员／游客角色、操作权限和知识库可见范围由 auth-facade 的 AuthService 提供；管理员证明校验由 auth-runtime 的 AuthRuntime 提供。接口见 [AUTH_INTERFACES.md](AUTH_INTERFACES.md)。auth-facade 依赖共享类型和 auth-runtime，auth-runtime 依赖共享类型及标准库；两者不依赖 Agent、RAG、Data 业务实现。HTTP 集成调用 auth-facade；管理员身份来自经验证的 owner 登录，游客只读公开资料。

DailyQueryQuota 通过注入的 StateStorePort 实施全站每日问答额度。DataService.state_db 返回的共享端口支持原子 increment_if_below，SQLite 事务位于 storage；额度业务不导入 data-facade 或 storage。
