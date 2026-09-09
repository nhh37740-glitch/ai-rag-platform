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

- 机器级"看不到源码"需要容器隔离（当前本地无 Docker）；本目录以"集成侧只 import 二进制 + 工作区不放实现源码 + 独立仓库/分支"实现操作/进程级隔离。
