from __future__ import annotations

import glob
import os
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Callable, List

from core_specifications import RequestContext

__version__ = "0.2.1"

_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
SUPPORTED_EXTENSIONS = frozenset({".md", ".txt", ".docx", ".pdf"})


def _split(text: str) -> List[str]:
    return [c.strip() for c in re.split(r"\n\s*\n", text) if c.strip()]


def _docx_text(path: str) -> str:
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml")
    root = ET.fromstring(xml)
    paragraphs = []
    for paragraph in root.iter(_NS + "p"):
        text = "".join(node.text or "" for node in paragraph.iter(_NS + "t")).strip()
        if text:
            paragraphs.append(text)
    return "\n\n".join(paragraphs)


def _pdf_pages(path: str) -> List[str]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("读取 PDF 需要安装 pypdf") from exc
    reader = PdfReader(path)
    return [text for page in reader.pages if (text := (page.extract_text() or "").strip())]


def parse(path: str) -> List[str]:
    ext = os.path.splitext(path)[1].lower()
    if ext in (".md", ".txt"):
        with open(path, encoding="utf-8", errors="ignore") as f:
            return _split(f.read())
    if ext == ".docx":
        return _split(_docx_text(path))
    if ext == ".pdf":
        return _pdf_pages(path)
    return []


def to_markdown(path: str, title: str = "") -> str:
    """Extract a supported document and normalize it into Markdown."""
    source = Path(path)
    extension = source.suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"不支持的文件类型: {extension or '(无扩展名)'}")

    display_title = (title or source.stem).strip().replace("\n", " ").replace("\r", " ")
    if extension == ".md":
        content = source.read_text(encoding="utf-8", errors="ignore").strip()
        if content.startswith("# "):
            return content + "\n"
        return f"# {display_title}\n\n{content}\n"

    sections = parse(str(source))
    if not sections:
        raise ValueError("文件中没有可提取的文本；扫描版 PDF 需要先进行 OCR")
    if extension == ".pdf" and len(sections) > 1:
        body = "\n\n".join(f"## 第 {index} 页\n\n{text}" for index, text in enumerate(sections, 1))
    else:
        body = "\n\n".join(sections)
    return f"# {display_title}\n\n{body}\n"


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
        if os.path.isfile(f) and os.path.splitext(f)[1].lower() in SUPPORTED_EXTENSIONS:
            texts = parse(f)
            chunks = chunk(texts)
            if chunks:
                store.add(os.path.basename(f), chunks, embed_fn(chunks))
                n += len(chunks)
    return n


__all__ = ["SUPPORTED_EXTENSIONS", "parse", "to_markdown", "chunk", "build_index"]
