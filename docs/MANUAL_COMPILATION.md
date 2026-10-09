# 手动编译与二进制交付

本页保留编译脚本的维护参考，不记录某次机器上的测试结果。日常发布由服务器 Jenkins 在 Docker builder 中完成；Codex 本机不执行编译。手动命令仅供维护构建流程时在匹配目标平台的隔离构建机使用。目标是把 `modules-src/` 中的实现发布为 `artifacts/<module-id>/<version>/` 下的二进制与接口规范。

## 1. 准备环境

在仓库根目录创建虚拟环境并按 [`README.md`](../README.md) 安装项目依赖。Windows 编译 `.pyd` 需要 MSVC Build Tools；Linux 编译 `.so` 需要 C 编译器。Dockerfile 在 Linux 构建阶段准备编译环境。

当前批量脚本和服务器 Jenkins 流水线均使用 Cython 编译进程内模块；仓库没有 mypyc 构建路径。

```powershell
uv pip install cython nuitka build
```

## 2. 编译进程内模块

```powershell
.\.venv\Scripts\python.exe scripts\compile_extension_modules.py
```

该脚本遍历 `modules-src/<module-id>/`，编译包入口，并把当前平台的 `.pyd` 或 `.so` 放入 `artifacts/<module-id>/<version>/<package>/`。

只改动了部分模块时，用 `--module` 只编译它们，未指定的模块保持原样：

```powershell
.\.venv\Scripts\python.exe scripts\compile_extension_modules.py --module rag-core --module rag-tools --module agent-runtime
```

## 3. 编译独立服务

```powershell
.\scripts\compile_service_executables.ps1
```

默认编译 `mcp-servers`；传入 `-All` 时同时编译 ingestion worker。可执行文件输出到被 Git 忽略的 `bin/`。

## 4. 生成发布元数据

```powershell
.\.venv\Scripts\python.exe scripts\package_release_artifacts.py
```

配合上一节时同样可以只刷新改动的模块，其余注册信息原样保留：

```powershell
.\.venv\Scripts\python.exe scripts\package_release_artifacts.py --module rag-core --module rag-tools --module agent-runtime
```

每个发布目录应包含：

- `INTERFACE.md`：公开接口说明。
- `API_SCHEMA.json`：机器可读接口。
- `VERSION`：模块版本。
- `CHANGELOG.md`：版本变化。
- `test_specification.py`：交付接口规范测试。
- `checksum.sha256`：源码快照校验和。
- `.pyd`、`.so` 或 `.exe`：实际二进制交付物。

脚本同步更新根目录 `registry.json`；检测到二进制时标记 `published`，否则标记 `contract-only`。

## 5. 由操作者验收

```powershell
.\.venv\Scripts\python.exe scripts\verify_compiled_runtime.py
.\.venv\Scripts\python.exe -m pytest specifications\test_specification.py
.\.venv\Scripts\python.exe scripts\build_release_bundle.py
```

`verify_compiled_runtime.py` 会复用 `apps/agent-server/runtime_boundary.py`，确认所有业务模块都来自 `artifacts/` 的编译产物；只要有一个模块来自 `modules-src`，服务与验收都会直接失败。

发布脚本按当前操作系统生成 `dist/ai-rag-platform-<version>-<platform>.zip`、独立 SHA-256 文件及清单，并重新读取 ZIP 验证所有条目校验和。Linux `.so` 交付必须在 Linux 构建机执行；Jenkinsfile 在 Docker 构建阶段完成这一步并归档产物。

仓库不提交 `build/`、`bin/`、本地数据库或一次性测试报告。
