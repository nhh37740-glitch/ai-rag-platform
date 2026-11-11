# scripts — 检查、测试、编译与部署

脚本按用途分组；所有路径解析以仓库根为基准。

## 结构、依赖与测试

| 脚本 | 用途 |
|---|---|
| `check_repo_structure.py` | 校验顶层层级、模块业务域归属、artifacts/registry 一致性和导航文档 |
| `check_module_dependencies.py` | 校验一级模块、业务 facade 与应用的导入方向 |
| `run_tests.py` | 按 source/binary 模式运行 leaf、facade、scripts、app、specification 测试 |
| `verify_compiled_runtime.py` | 校验运行时只从 `artifacts/` 加载二进制 |
| `verify_live_model.py` | 真实模型门禁 |

## 编译与发布

| 脚本 | 用途 |
|---|---|
| `compile_extension_modules.py` | 把 `modules-src/<域>/<模块>` 编译成 `artifacts/<模块>/<版本>` |
| `package_release_artifacts.py` | 刷新 `registry.json` 与模块接口元数据 |
| `build_release_bundle.py` | 生成版本化 ZIP（不含模块源码和凭据） |
| `compile_service_executables.ps1` | Windows Nuitka 可执行文件构建 |

## 部署与运维

| 脚本 | 用途 |
|---|---|
| `deploy_compose.sh` | 构建候选镜像、健康检查、切换 `ai-rag-agent-1` |
| `switch_rag_gateway.py` | 切换 nginx 的 RAG 路由 |
| `smoke_model_config.py` | 不消耗问答额度的线上模型配置检查 |
| `set_openrouter_key.sh` | 校验并替换 OpenRouter Key，重建容器（不输出密钥） |
| `run_ci_check.sh` | 在容器内运行测试并保留失败报告 |

## 开发约定

- 新增模块时，先在 `repo_layout.py` 的 `MODULE_GROUPS` 登记业务域。
- 修改目录层级后运行 `python scripts/check_repo_structure.py` 和
  `python scripts/check_module_dependencies.py`。
- 脚本中的凭据只从环境或权限受限文件读取，不写入命令行参数、日志或仓库。
