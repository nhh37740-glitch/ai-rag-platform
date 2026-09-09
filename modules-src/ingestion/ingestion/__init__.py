from __future__ import annotations

import glob
import os
import re
import zipfile
import xml.etree.ElementTree as ET
from typing import Callable, List

from core_contracts import RequestContext

__version__ = "0.1.0"

_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _split(text: str) -> List[str]:
    return [c.strip() for c in re.split(r"\n\s*\n", text) if c.strip()]


def _docx_text(path: str) -> str:
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml")
    root = ET.fromstring(xml)
    return "\n".join(t.text or "" for t in root.iter(_NS + "t"))


def parse(path: str) -> List[str]:
    ext = os.path.splitext(path)[1].lower()
    if ext in (".md", ".txt"):
        with open(path, encoding="utf-8", errors="ignore") as f:
            return _split(f.read())
    if ext == ".docx":
        return _split(_docx_text(path))
    if ext == ".pdf":
        return []  # 待接入 pdf 库；接口已预留
    return []


def chunk(texts: List[str], size: int = 500, overlap: int = 50) -> List[str]:
    out: List[str] = []
    for t in texts:
        i = 0
        while i < len(t):
            if i > 0 and len(t) - i <= overlap:
                break
            out.append(t[i : i + size])
            i += max(1, size - overlap)
    return out


def build_index(ctx: RequestContext, docs_dir: str, store, embed_fn: Callable[[List[str]], List[List[float]]]) -> int:
    n = 0
    for f in sorted(glob.glob(os.path.join(docs_dir, "*"))):
        if os.path.isfile(f) and os.path.splitext(f)[1].lower() in (".md", ".txt", ".docx"):
            texts = parse(f)
            chunks = chunk(texts)
            if chunks:
                store.add(os.path.basename(f), chunks, embed_fn(chunks))
                n += len(chunks)
    return n


__all__ = ["parse", "chunk", "build_index"]
