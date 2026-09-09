# 二进制交付构建说明

目标：让集成侧只 import 编译后成品（`.pyd/.so/.exe`），看不到源码。当前仓库以离线纯 Python 实现并跑通；本文件给出编译步骤（需 MSVC 与对应工具链）。

## 进程内模块（import 的 `.pyd/.so`）

用 [mypyc](https://mypyc.readthedocs.io/)（默认）：

```bash
uv pip install mypyc
cd modules-src/<module>
mypyc --package <pkg>          # 产出 <pkg>*.pyd (Windows) / .so (Linux)
```

若模块用了 mypyc 不支持的动态特性，回退 Cython：

```bash
uv pip install cython
cd modules-src/<module>
cythonize -i <pkg>/*.py        # 或写 pyproject 用 setuptools 构建扩展
```

## 独立进程模块（Nuitka 可执行）

```bash
uv pip install nuitka
nuitka --standalone --onefile modules-src/mcp-servers/mcp_servers/__main__.py --output-filename=mcp_servers.exe
# ingestion-worker 同理
```

## 打包与校验

```bash
python -m build modules-src/<module>      # 产 wheel，作"库"交付
python scripts/build_artifacts.py         # 生成 artifacts/<pkg>/<version>/ + registry.json + checksum
```

## 交付清单（artifacts/<pkg>/<version>/）

`INTERFACE.md`、`API_SCHEMA.json`、`VERSION`、`CHANGELOG.md`、`test_contract.py`、`checksum.sha256`，以及编译成品（`*.pyd/.so/.exe`）。

## 已知限制

- 机器级"看不到源码"需要容器隔离（本机无 Docker）；本目录以"集成侧只 import 二进制 + 工作区不放实现源码 + 独立仓库/分支"实现操作/进程级隔离。

## 已验证（2026-09-10，本机）

- MSVC 编译器在 `C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools`（cl.exe 14.44）。
- **Cython 3.3 路线可用**：`cythonize -i modules-src/<mod>/<pkg>/__init__.py` 产出 `__init__.<abi>.pyd`。
- 已用 **observability** 做证明：把编译产物的 `.pyd` 单独放进 `artifacts/observability/0.1.0/observability/`（该目录无 `.py`），`scripts/binary_demo.py` 将其置于 `sys.path[0]` 后 `import observability`，`__file__` 指向 `.pyd`，功能正常→ `BINARY_DELIVERY_OK`。
- mypyc 路线需前置 `mypy`+`librt`，并以 `--no-build-isolation` 安装；本机此路线较曲折，故二进制优先用 Cython。
