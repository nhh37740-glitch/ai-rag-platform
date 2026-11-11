# artifacts — 编译产物与发布视图

本目录是**只读交付层**：集成侧运行时只从这里加载模块二进制，不读 `modules-src/`。
目录按模块 ID 和版本组织，`registry.json` 是唯一索引。

```text
artifacts/
└── <module-id>/
    └── <version>/
        ├── <package>/            # .pyd / .so 二进制
        ├── VERSION
        ├── INTERFACE.md
        ├── API_SCHEMA.json
        ├── CHANGELOG.md
        ├── checksum.sha256
        └── test_specification.py
```

## 规则

- 不要手工修改本目录；由 `scripts/compile_extension_modules.py` 编译、
  `scripts/package_release_artifacts.py` 登记。
- 运行时由 `apps/ragnotebook/runtime_boundary.py` 读取 `registry.json`，只把
  `published` 模块的 `artifacts` 路径加入 `sys.path`，并校验模块确实来自二进制。
- 模块版本目录只增不改；新版本发布后更新 `registry.json`，不要移动旧版本目录。
- 发布包（`scripts/build_release_bundle.py`）只收集 `artifacts/`、`apps/`、
  `specifications/`、`skills/` 等运行资产，不包含 `modules-src/`。

## 阅读建议

想看源码请回到 `modules-src/<业务域>/<module-id>/`；本目录只回答“运行时加载的是哪个
版本、哪个二进制、校验和是多少”。
