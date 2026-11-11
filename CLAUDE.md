# CLAUDE.md

本文件给 Claude Code 提供仓库级工作约定。**唯一事实来源**是
[`docs/PLAN.md`](docs/PLAN.md)、[`AGENTS.md`](AGENTS.md) 和
[`specifications/INTERFACES.md`](specifications/INTERFACES.md)；改方案先改文档，再动代码。

## 项目是什么

RAGnotebook：面向浏览器的文档问答应用。单进程 FastAPI 服务，内部组合四个业务 facade：

- `auth-facade`：账号、登录、额度、权限
- `data-facade`：唯一 SQLite（六张表）、向量与记忆
- `rag-facade`：解析、分块、检索、来源
- `agent-facade`：模型选择、问答编排、工具与技能

浏览器只调用 HTTP API；模型密钥只从服务器环境读取。

## 目录

```text
specifications/        接口规范（唯一共享源码）
modules-src/<域>/      模块源码，仅构建阶段可见
  agent/ rag/ data/ auth/ platform/
artifacts/<模块>/<版本>/  编译产物，运行时只读
apps/ragnotebook/      集成服务（HTTP + 运行时边界）
apps/web/              浏览器页面
scripts/               检查、测试、编译、部署、运维
docs/                  方案、架构、验证与运维文档
registry.json          模块版本/checksum/产物路径索引
```

完整导航见 [`docs/CODE_TREE.md`](docs/CODE_TREE.md)。模块新增或移动时，先更新
`scripts/repo_layout.py` 的 `MODULE_GROUPS`，再更新对应 `README.md` 和 `CODE_TREE.md`。

## 常用命令

```bash
# 结构与边界
python scripts/check_repo_structure.py
python scripts/check_module_dependencies.py

# 源码测试（需要 Python 3.11+ 与模块依赖）
python scripts/run_tests.py --mode source --group leaf
python scripts/run_tests.py --mode source --group facade
python scripts/run_tests.py --mode source --group scripts
python scripts/run_tests.py --mode binary --group specification
python scripts/verify_compiled_runtime.py
```

完整构建/测试在 Docker 多阶段与 Jenkins 中执行；本机没有依赖时不要假装测试通过。

## 架构红线

- 应用（`apps/ragnotebook`）只导入四个业务 facade 和共享公共接口；**禁止**直接导入
  一级模块、SQLite、向量或记忆实现。
- 业务域之间不直接导入实现；跨域服务通过注入的 Protocol。
- `auth-runtime` 只允许 `core_specifications` 和标准库。
- 运行时只从 `artifacts/` 加载 `.pyd/.so`；`runtime_boundary.py` 会拒绝从
  `modules-src/` 或 `.py` 加载的模块。
- 只使用一个 SQLite 文件和冻结的六张表；禁止第二个 DB、额外业务表或自动迁移。
- 游客问答不持久化；所有身份共享每日 100 次额度；登录令牌只在进程内。
- 密钥只从服务器环境读取，不写入仓库、镜像、日志、接口响应或终端输出。

## 部署与运维

- `compose.yaml` 定义单服务 `agent`，镜像 `ai-rag-platform:local`，监听
  `127.0.0.1:18080`。
- Jenkins 作业 `ai-rag-platform` 的 `DeployDemo=true` 才会发布；没有自动触发。
- OpenRouter Key 轮换：

  ```bash
  sudo scripts/set_openrouter_key.sh
  ```

  脚本从标准输入读取 Key，在线校验后原子替换环境文件，并重建 `ai-rag-agent-1`。
- 部署使用候选镜像 + 健康检查 + 切换；失败时保留数据卷，不自动恢复旧服务。

## 提交与 PR

- 使用 Conventional Commits：`feat:` `fix:` `docs:` `test:` `build:` `refactor:`。
- 每个版本从 `master` 建独立分支，完成后通过 PR 合回；发布后补 tag。
- PR 描述按「RAGnotebook → 业务模块 → 本次修改的一级模块」说明；未修改的模块标“沿用”。
- 模块改动同时更新 `VERSION`、`CHANGELOG.md`、`API_SCHEMA.json`，并重建二进制与 checksum。
- 提交前运行结构与依赖检查；不要提交 `.env*`、密钥、`dist/`、`reports/`。

## Issue 工作流

1. `gh issue view <n> -R nhh37740-glitch/ai-rag-platform` 读验收标准；
2. 从 `master` 建分支（如 `fix/37-...`、`refactor/38-...`）；
3. 实现 + 测试 + 文档，必要时在服务器上运行 Linux 测试；
4. 推送分支、开 PR，在 PR 中逐条对照验收标准；
5. 合并后关闭 issue，并记录验证证据。
