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
