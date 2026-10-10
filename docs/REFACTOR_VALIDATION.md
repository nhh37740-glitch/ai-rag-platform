# 三个中间模块重构验收（2026-10-09）

本次已定义接口规范和测试输入/断言，由三个 subagent 分别完成 AGENT、RAG、数据库域；协调侧完成接口目录迁移、服务装配、Web 拆分、构建入口、分层检查和统一验收。以下保留各阶段验收记录；最新 0.5.0 已合入 GitHub 并完成服务器及主页发布，结果见末尾。

## 已交付

- `specifications/`、`core_specifications`、`test_specification.py`、`SPEC_STRICT` 替代旧名称。完整中间接口/错误行为/生命周期/验收用例见 `specifications/DOMAIN_INTERFACES.md`，机器签名见 `API_SCHEMA.json`。
- `agent-facade` 0.1.0：注入跨域 Protocol，装配 AgentRuntime、工具、技能；五个 RAG 工具自动注册且不能被覆盖，模型不能扩大请求范围，历史快照隔离，关闭幂等。
- `rag-facade` 0.1.0：文件转换、分块、入库、三种检索、分页读取、工具执行及 trace；显式范围、空范围、非法参数和越界访问均有检查。
- `data-facade` 0.1.0：管理 memory/vector/state 连接与持久化；SQLite 向量实现迁到 storage，不依赖 rag_core；原子替换、事务回滚、向量维度/数值检查、锁和生命周期已验证。
- `apps/agent-server` 0.4.0 只装配三个中间包及公共层；`apps/web/` 是随包交付的静态前端，仅调用 API。
- AGENT runtime、RAG core、memory/storage 及接口改名涉及的一级包均更新版本和 CHANGELOG。所有16个注册模块已生成 Windows `.pyd`、接口元数据和 checksum；源码 VERSION、pyproject、规范和注册表保持一致。
- 自动依赖检查拒绝应用引用叶子、数据库引用 RAG、叶子引用中间包及同域循环；支持字面量动态 import 检查。源码测试显式强制加载 `.py`，二进制测试只加载注册 `.pyd/.so`。
- Jenkins 分步显示检查/测试/编译/真实模型/打包/发布，保存 JUnit（包括失败容器内报告）。每次真实模型调用在新容器执行，不受 Docker 层缓存跳过；凭据只通过临时环境文件注入，不进入镜像。部署参数仍默认 false。

## 实际验证结果

下表统计 pytest 主用例，subtests 另由 XML 记录，不重复计数。

| 验证 | 结果 | 报告 |
|---|---|---|
| 一级模块源码 | 89 通过 | reports/source-leaf.xml |
| 三个中间包源码 | 29 通过 | reports/source-facade.xml |
| 三域源码集成/分层负向检查 | 7 通过 | reports/source-domain.xml |
| 一级模块 Windows 二进制行为回放 | 89 通过 | reports/binary-leaf.xml |
| 三个中间包 Windows 二进制回放 | 29 通过 | reports/binary-facade.xml |
| 三域 Windows 二进制集成/分层检查 | 7 通过 | reports/binary-domain.xml |
| 严格接口、包内规范及版本元数据 | 12 通过 | reports/specification.xml |
| 最终 HTTP 服务/上传/公开边界/网页 | 15 通过 | reports/app.xml |
| 六项 POSIX 部署回滚（现有 WSL Ubuntu） | 6 通过 | reports/posix-deployment.xml |
| 真实 DeepSeek 两道固定题 | 1 主用例、2 个题目 subtests 通过 | reports/live-model.xml |
| 五个 RAG 工具、入库和问答冒烟 | COMPILED_AGENT_OK，16个模块来自 artifacts | scripts/verify_compiled_runtime.py |
| 发布包独立解压启动 | 静态资源、24文档、问答、实际 trace 通过 | reports/release-http.log |

检索使用明确的 hash embedding：CMRC 24篇文档、99题、Top-5 期望来源命中保持向量95/99、词面99/99、融合99/99。不是 BGE 模型质量评测。真实 DeepSeek 验收两题分别覆盖静电感应与奥卡姆剃刀，断言实际检索、期望文档、引用标记以及答案核心内容；仅连接错误允许重试一次，其他失败仍阻断。

Windows原生运行POSIX fixture失败的诊断保存在 reports/diagnostics；未降低断言。改用真实 Linux 运行后通过，并修复工作区 shell 的 CRLF，增加 `.gitattributes` 的 LF 规则。另修复旧异步测试对全局事件循环的依赖及两处 SQLite 测试连接泄漏。

源码行为测试、Windows 编译使用本机 Python3.11 / Cython3.3 / pytest9.1；WSL Ubuntu Python3.12 回放纯Python部署测试。服务器 Docker 仍按 requirements-build.txt 安装自身依赖，因此不能把本地结果当作远端构建结果。

## 发布包与待执行项

Windows包：`dist/ai-rag-platform-0.4.0-win-amd64.zip`，166个文件，16个模块版本。SHA-256：`e6175a0dc58877f1fe58bfcc25cdee72fe984526f8e12a820b3939d1dfe1a9ed`。清单和外层 SHA 文件随包生成；包含 apps/web，不包含 modules-src、环境文件或本地加密凭据。

初次记录时服务器 Jenkins 尚未执行本次修改。构建需 secret text 凭据 ID `rag-deepseek-api-key`，缺凭据时真实模型阶段明确失败。用户提供的 key 已在本机 Windows 用户加密文件保存。

### 2026-10-10 追加 GitHub 与服务器交付

- PR #2 已合入 master，提交 `6e84a8be807f9c28f3b583772aec3afb87e17826`；PR #1 因完整包含在新 PR 中关闭。整合了远端 `23bb124` 的管理员登录/工作区及新版公开页面。
- 应用 0.4.1 加入公开页面手动临时 key：同源 HTTPS/回环校验、请求 ContextVar 清理、异常数据清理、绕过共享缓存。无 key 明确 Mock，全部静态资源在 apps/web。
- 服务测试 27 项通过，管理员测试中的 Mock 检索提示修正后所属 5 项复验通过（完整集合共28项）。没有降低导入后真实来源、身份或私有范围断言。WSL 实际 POSIX 回滚共9项通过。
- 更新 Windows 包 `dist/ai-rag-platform-0.4.1-win-amd64.zip`，172文件/16模块，SHA-256 `b4c0792a0943e6a47cfc46e192eade62df7905b5289f6ab70b34cbf2c53bc08b`。
- Jenkins #15 已准确获取 master `6e84a8b`，Linux流水线最终SUCCESS：源码与二进制一级89/中间29、严格12、应用28、POSIX回滚及真实模型两题全部通过，公開Mock候选与正式发布通过。
- 自动审批最初拒绝远端 Jenkins 保存 key；用户随后对明确授权问题回复“授权”。已通过 SSH 成功配置构建专用 Secret Text `rag-deepseek-api-key`，未写入运行镜像/容器。#15 已通过真实模型门禁并完成公开发布。

### 追加鉴权0.5.0（2026-10-10 发布完成）

新增 auth-runtime0.1.0 与共享AuthPrincipal/AuthServicePort，固定A01-A08验收。Windows17扩展严格契约12+143子测试、编译权限与RAG冒烟通过；源/二进制鉴权非法输入 parity 修复；应用29测试通过。

- RAG PR #3 已合入 master，合并提交 `cb297cf21195751ff40fa2fa845b534ec1e49e04`。Jenkins #17 获取公开 smoke Unicode URL 修复提交 `9ba5b05ce1b4aa44715143965232a6c9d97266cb`，全部源码/二进制、依赖、严格规范、HTTP、编译运行来源及真实 DeepSeek 两题门禁通过，公开发布成功。该任务最终 FAILED 原因为管理员旧 smoke 错将游客公开笔记本读取 200 视为失败，不能将 #17 整体记为成功。
- 修复提交 `851cf2c2caf058c83e9a5e6476d71dfecbb38392` 已推送 master，更新游客读取断言，继续检查写入与私有范围拒绝；部署支持显式复用已验证不可变镜像。Jenkins `rag-admin-recovery-17 #2` SUCCESS：核验 #17 全部门禁、修复范围及镜像身份，6项 Linux 回滚测试通过，候选创建笔记本→导入→真实来源检索通过，正式管理员/login 容器发布并健康。
- 实际复用镜像 `sha256:d3adce6eda826c8beeedf21b04085708d6b0d51f52b53b62067f8ad3d4d0aa86`。公開与管理员 agent 实测应用 0.5.0、17个编译模块、模块源码不存在。公开 agent、管理员 agent、登录容器均未配置模型 key。
- 主页 PR #1 合入 main `e07ab9b15934f80d136e57ec62ee298ecee57dff`，Jenkins `project-index #28` SUCCESS，0.5.0 卡片与管理反代已发布。管理入口 `https://portfolio.72945645.xyz:8443/projects/apps/rag/admin/login`；无需新增 443 监听。
- 正式 HTTPS 8443 验证通过：游客公开资料读取及自由查询有实际 trace，游客创建/导入和私有访问被拒绝；owner 经现有 Media 服务实际登录，返回管理员创建/导入权限，读取管理笔记本成功，退出后再次访问被拒绝。正式环境验证只读取、登录/退出；写入与导入在候选环境验证。
- 最新 Windows 包 `dist/ai-rag-platform-0.5.0-win-amd64.zip`，17个模块。SHA-256 `4004ad395a1ce0ae8a5f1ae27f010af5191976605a1d9d8812c3c3404ed9ef76`；包含静态 Web，不包含模块源码、环境文件或本地凭据。

线上默认为 Mock/hash；构建专用凭据只用于 Jenkins 真实模型门禁。Web 手动临时 key 的线上真实调用由用户测试，未列为本轮已验证结果。
