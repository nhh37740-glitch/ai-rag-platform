# 手动编译与二进制交付

本页只描述操作者需要执行的顺序，不记录某次机器上的测试结果。目标是把 `modules-src/` 中的实现发布为 `artifacts/<module-id>/<version>/` 下的二进制与契约。

## 1. 准备环境

在仓库根目录创建虚拟环境并按 [`README.md`](../README.md) 安装项目依赖。Windows 编译 `.pyd` 还需要可用的 MSVC Build Tools。

当前批量脚本使用 Cython；mypyc 是目标默认方案，模块遇到不支持的动态特性时可继续使用 Cython 回退。

```powershell
uv pip install cython nuitka build
```

## 2. 编译进程内模块

```powershell
.\.venv\Scripts\python.exe scripts\compile_extension_modules.py
```

该脚本遍历 `modules-src/<module-id>/`，编译包入口，并把 `.pyd` 放入 `artifacts/<module-id>/<version>/<package>/`。

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
- `test_contract.py`：交付契约测试。
- `checksum.sha256`：源码快照校验和。
- `.pyd`、`.so` 或 `.exe`：实际二进制交付物。

脚本同步更新根目录 `registry.json`；检测到二进制时标记 `published`，否则标记 `contract-only`。

## 5. 由操作者验收

```powershell
.\.venv\Scripts\python.exe scripts\verify_compiled_runtime.py
.\.venv\Scripts\python.exe -m pytest contracts\test_contract.py
```

`verify_compiled_runtime.py` 会复用 `apps/agent-server/runtime_boundary.py`，确认所有业务模块都来自 `artifacts/` 的编译产物；只要有一个模块来自 `modules-src`，服务与验收都会直接失败。

仓库不提交 `build/`、`bin/`、本地数据库或一次性测试报告。
