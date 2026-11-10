## 0.3.0 - 2026-11-10

- 新增 `chunk_tokens`：中文按字、英文按词近似 token 计数，不再把字符数说成 token 数。
- 新增 `chunk_structural`：按段落打包，超长段落回退到 token 切块，保留段落边界。
- 新增 `chunk_with_strategy`，用于离线对照实验；原 `chunk` 保持字符滑动窗口基线。
- `build_index` 可选注入 chunker，默认行为不变。

## 0.2.2 - 2026-10-14

- DOCX ZIP/XML/缺失正文和PDF解析/加密错误统一为ValueError，让调用方结束失败进度并返回可理解的校验错误。
- 有效文件、公共签名与系统文件错误保持既有行为。

# 0.2.1
- 共享接口包迁移为 core_specifications；重新构建二进制并保持本模块接口行为。

# Changelog

## [0.2.0]
- 支持 PDF 文本提取，并将 Markdown、TXT、DOCX、PDF 统一转换为 Markdown 后入库。

## [0.1.0]
- 初始化文档解析、分块与索引能力。
