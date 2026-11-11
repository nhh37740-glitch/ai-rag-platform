# ingestion

文档入库：支持 `.md`、`.txt`、`.docx`、`.pdf`，先由 `to_markdown` 统一转换为 Markdown，再分块、向量化并写入指定知识库。

切块策略：

- `chunk`：字符滑动窗口，历史基线；500/50 是字符数，不是 token 数。
- `chunk_tokens`：近似 token 滑动窗口，中文按字、英文按词。
- `chunk_structural`：按段落打包，超长段落回退到 token 切块。
- `chunk_with_strategy`：实验入口，不改变默认入库行为。

扫描版 PDF 不包含可提取文字，需要先在外部完成 OCR。
