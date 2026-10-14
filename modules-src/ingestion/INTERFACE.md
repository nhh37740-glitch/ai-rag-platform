# INTERFACE

- `parse(path) -> list[str]`
- `to_markdown(path, title='') -> str`
- `chunk(texts, size=500, overlap=50) -> list[str]`
- `build_index(ctx, docs_dir, store, embed_fn) -> int`

- parse/to_markdown：损坏DOCX（ZIP/XML/缺失正文）、损坏或加密PDF抛ValueError，错误不包含文件正文；不存在/无权限等文件系统错误保持原异常。不忽略损坏来源。
