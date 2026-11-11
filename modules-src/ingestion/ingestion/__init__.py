from __future__ import annotations

import glob
import os
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Callable, List

from core_specifications import RequestContext

__version__ = "0.3.0"

_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
SUPPORTED_EXTENSIONS = frozenset({".md", ".txt", ".docx", ".pdf"})


def _split(text: str) -> List[str]:
    return [c.strip() for c in re.split(r"\n\s*\n", text) if c.strip()]


def _docx_text(path: str) -> str:
    try:
        with zipfile.ZipFile(path) as z:
            xml = z.read("word/document.xml")
        root = ET.fromstring(xml)
    except (zipfile.BadZipFile, ET.ParseError, KeyError, RuntimeError) as exc:
        raise ValueError("DOCX 文件损坏或缺少可读取的正文") from exc
    paragraphs = []
    for paragraph in root.iter(_NS + "p"):
        text = "".join(node.text or "" for node in paragraph.iter(_NS + "t")).strip()
        if text:
            paragraphs.append(text)
    return "\n\n".join(paragraphs)


def _pdf_pages(path: str) -> List[str]:
    try:
        from pypdf import PdfReader
        from pypdf.errors import PyPdfError
    except ImportError as exc:
        raise RuntimeError("读取 PDF 需要安装 pypdf") from exc
    try:
        reader = PdfReader(path)
        if reader.is_encrypted:
            raise ValueError("PDF 已加密，请上传未加密的 PDF")
        return [text for page in reader.pages if (text := (page.extract_text() or "").strip())]
    except PyPdfError as exc:
        raise ValueError("PDF 文件损坏或无法读取正文") from exc


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
    """Character sliding window; the historical baseline.

    ``size`` and ``overlap`` count Unicode characters, not model tokens.
    """
    out: List[str] = []
    for t in texts:
        i = 0
        while i < len(t):
            if i > 0 and len(t) - i <= overlap:
                break
            out.append(t[i : i + size])
            i += max(1, size - overlap)
    return out


_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[一-鿿]")


def _token_spans(text: str) -> List[tuple[int, int]]:
    """Approximate model tokens: one per Latin word/number or Chinese character."""
    return [(match.start(), match.end()) for match in _TOKEN_RE.finditer(text)]


def chunk_tokens(texts: List[str], size: int = 500, overlap: int = 50) -> List[str]:
    """Token-approximate sliding window.

    Chinese characters count as one token and Latin words/numbers as one token.
    Punctuation and whitespace do not consume the budget but stay inside the
    returned slice, so the text remains readable.
    """
    if size < 1:
        raise ValueError("size 必须大于 0")
    if overlap < 0 or overlap >= size:
        raise ValueError("overlap 必须在 0 到 size-1 之间")
    out: List[str] = []
    for text in texts:
        spans = _token_spans(text)
        if not spans:
            continue
        start = 0
        while start < len(spans):
            end = min(len(spans), start + size)
            out.append(text[spans[start][0] : spans[end - 1][1]].strip())
            if end >= len(spans):
                break
            start = end - overlap
    return [item for item in out if item]


def chunk_structural(texts: List[str], size: int = 500, overlap: int = 50) -> List[str]:
    """Paragraph-aware packing with a token-approximate budget.

    Paragraphs are never silently dropped. A paragraph larger than ``size`` is
    split with :func:`chunk_tokens`. When a new paragraph would exceed the
    budget, the previous chunk is emitted and its last ``overlap`` tokens are
    carried into the next chunk as context.
    """
    if size < 1:
        raise ValueError("size 必须大于 0")
    if overlap < 0 or overlap >= size:
        raise ValueError("overlap 必须在 0 到 size-1 之间")
    out: List[str] = []
    for text in texts:
        paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
        if not paragraphs:
            continue
        current = ""
        for paragraph in paragraphs:
            if len(_token_spans(paragraph)) > size:
                if current:
                    out.append(current)
                    current = ""
                out.extend(chunk_tokens([paragraph], size=size, overlap=overlap))
                continue
            candidate = (current + "\n\n" + paragraph).strip() if current else paragraph
            if current and len(_token_spans(candidate)) > size:
                out.append(current)
                allowed_overlap = max(0, size - len(_token_spans(paragraph)))
                tail = _token_spans(current)[-allowed_overlap:] if allowed_overlap else []
                prefix = current[tail[0][0] :] if tail else ""
                current = (prefix + "\n\n" + paragraph).strip()
            else:
                current = candidate
        if current:
            out.append(current)
    return out


def chunk_with_strategy(
    texts: List[str],
    strategy: str = "char",
    size: int = 500,
    overlap: int = 50,
) -> List[str]:
    """Select the baseline (``char``), ``token`` or ``structural`` chunker."""
    normalized = strategy.strip().lower()
    if normalized == "char":
        return chunk(texts, size=size, overlap=overlap)
    if normalized == "token":
        return chunk_tokens(texts, size=size, overlap=overlap)
    if normalized == "structural":
        return chunk_structural(texts, size=size, overlap=overlap)
    raise ValueError(f"不支持的切块策略: {strategy!r}")


def build_index(
    ctx: RequestContext,
    docs_dir: str,
    store,
    embed_fn: Callable[[List[str]], List[List[float]]],
    chunker: Callable[[List[str]], List[str]] = chunk,
) -> int:
    n = 0
    for f in sorted(glob.glob(os.path.join(docs_dir, "*"))):
        if os.path.isfile(f) and os.path.splitext(f)[1].lower() in SUPPORTED_EXTENSIONS:
            texts = parse(f)
            chunks = chunker(texts)
            if chunks:
                store.add(os.path.basename(f), chunks, embed_fn(chunks))
                n += len(chunks)
    return n


__all__ = [
    "SUPPORTED_EXTENSIONS",
    "parse",
    "to_markdown",
    "chunk",
    "chunk_tokens",
    "chunk_structural",
    "chunk_with_strategy",
    "build_index",
]
