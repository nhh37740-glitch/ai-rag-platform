# ingestion

文档入库：支持 `.md`、`.txt`、`.docx`、`.pdf`，先由 `to_markdown` 统一转换为 Markdown，再分块、向量化并写入指定知识库。

扫描版 PDF 不包含可提取文字，需要先在外部完成 OCR。
