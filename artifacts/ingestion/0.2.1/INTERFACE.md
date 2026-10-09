# INTERFACE

- `parse(path) -> list[str]`
- `to_markdown(path, title='') -> str`
- `chunk(texts, size=500, overlap=50) -> list[str]`
- `build_index(ctx, docs_dir, store, embed_fn) -> int`
