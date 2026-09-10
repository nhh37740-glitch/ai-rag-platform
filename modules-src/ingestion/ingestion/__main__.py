from __future__ import annotations

import glob
import json
import os
import sys
from pathlib import Path
from typing import List

from ingestion import SUPPORTED_EXTENSIONS, chunk, parse


def _load_dotenv(path: str) -> None:
    import os as _os

    if not _os.path.exists(path):
        return
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            _os.environ.setdefault(k.strip(), v.strip())


def main(argv: List[str] | None = None) -> int:
    """独立进程：解析一个目录→分块→embed→写出索引 JSON，供主进程加载。"""
    _load_dotenv(str(Path(__file__).resolve().parents[2] / ".env"))
    args = sys.argv[1:] if argv is None else argv
    docs_dir = "data/kb"
    out = "data/index.json"
    if args and not args[0].startswith("--"):
        docs_dir = args[0]
    if "--out" in args:
        out = args[args.index("--out") + 1]

    from rag_core import embed  # 运行时导入，避免硬耦合

    sources = []
    total = 0
    for f in sorted(glob.glob(os.path.join(docs_dir, "*"))):
        if os.path.splitext(f)[1].lower() in SUPPORTED_EXTENSIONS:
            chunks = chunk(parse(f))
            if chunks:
                sources.append({"id": os.path.splitext(os.path.basename(f))[0], "chunks": chunks, "embs": embed(chunks)})
                total += len(chunks)
    os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump({"embed": os.environ.get("RAG_EMBED", "hash"), "sources": sources, "total_chunks": total}, fh, ensure_ascii=False)
    print(f"ingested {total} chunks from {docs_dir} -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
