# INTERFACE

- `parse(path) -> list[str]`
- `to_markdown(path, title='') -> str`
- `chunk(texts, size=500, overlap=50) -> list[str]`：字符滑动窗口基线。
- `chunk_tokens(texts, size=500, overlap=50) -> list[str]`：近似 token 滑动窗口；中文按字、英文按词计数。
- `chunk_structural(texts, size=500, overlap=50) -> list[str]`：按段落打包，超长段落回退到 `chunk_tokens`。
- `chunk_with_strategy(texts, strategy, size=500, overlap=50) -> list[str]`：`char`/`token`/`structural`。
- `build_index(ctx, docs_dir, store, embed_fn, chunker=chunk) -> int`

- parse/to_markdown：损坏DOCX（ZIP/XML/缺失正文）、损坏或加密PDF抛ValueError，错误不包含文件正文；不存在/无权限等文件系统错误保持原异常。不忽略损坏来源。
- 所有 size/overlap 都按所选单位计数；只有 `chunk` 的单位是字符，不能对外称 token。
