import os
import pathlib
import shutil
import unittest
import tempfile
import zipfile
from pypdf import PdfWriter

from core_specifications import RequestContext
from ingestion import (
    build_index,
    chunk,
    chunk_structural,
    chunk_tokens,
    chunk_with_strategy,
    parse,
    to_markdown,
)


class TestIngestion(unittest.TestCase):
    def test_invalid_docx_zip_xml_and_missing_body_are_document_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "broken.docx"
            path.write_bytes(b"not a ZIP")
            for entry in (None, "missing", "xml"):
                if entry is not None:
                    with zipfile.ZipFile(path, "w") as archive:
                        archive.writestr("other.xml" if entry == "missing" else "word/document.xml", "<bad")
                for operation in (parse, to_markdown):
                    with self.subTest(entry=entry, operation=operation.__name__):
                        with self.assertRaisesRegex(ValueError, "DOCX"):
                            operation(str(path))

    def test_invalid_and_encrypted_pdf_are_document_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "broken.pdf"
            path.write_bytes(b"not a PDF")
            for operation in (parse, to_markdown):
                with self.assertRaisesRegex(ValueError, "PDF"):
                    operation(str(path))
            writer = PdfWriter()
            writer.add_blank_page(width=72, height=72)
            writer.encrypt("private-test-password")
            with path.open("wb") as handle:
                writer.write(handle)
            for operation in (parse, to_markdown):
                with self.assertRaisesRegex(ValueError, "已加密"):
                    operation(str(path))

    def test_missing_files_keep_filesystem_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            for extension in ("docx", "pdf"):
                with self.assertRaises(FileNotFoundError):
                    parse(str(pathlib.Path(directory) / ("missing." + extension)))

    def test_chunk(self):
        out = chunk(["abcdefghij"], size=4, overlap=1)
        self.assertEqual(out, ["abcd", "defg", "ghij"])

    def test_token_chunk_counts_chinese_characters(self):
        out = chunk_tokens(["静电感应是物体内的电荷重新分布"], size=5, overlap=1)
        self.assertEqual(out[0], "静电感应是")
        self.assertEqual(out[1][0], "是")
        self.assertGreaterEqual(len(out), 3)

    def test_token_chunk_counts_latin_words(self):
        out = chunk_tokens(["one two three four five"], size=2, overlap=0)
        self.assertEqual(out, ["one two", "three four", "five"])

    def test_structural_chunk_keeps_paragraph_boundaries(self):
        text = "第一段内容。\n\n第二段内容。\n\n第三段内容。"
        out = chunk_structural([text], size=6, overlap=1)
        self.assertTrue(all(part for part in out))
        self.assertIn("第一段内容。", out[0])
        self.assertTrue(any("第三段内容。" in part for part in out))

    def test_structural_splits_oversized_paragraph(self):
        out = chunk_structural(["一二三四五六七八九十"], size=3, overlap=1)
        self.assertGreaterEqual(len(out), 2)
        self.assertEqual("".join(out)[:3], "一二三")

    def test_chunk_strategy_dispatch_and_validation(self):
        self.assertEqual(chunk_with_strategy(["abcdefghij"], "char", 4, 1), ["abcd", "defg", "ghij"])
        self.assertEqual(chunk_with_strategy(["one two three four five"], "token", 2, 0), ["one two", "three four", "five"])
        with self.assertRaises(ValueError):
            chunk_with_strategy(["x"], "unknown")

    def test_parse_txt(self):
        d = pathlib.Path("data/_tests"); d.mkdir(parents=True, exist_ok=True)
        f = d / "kb.txt"
        f.write_text("第一段。\n\n第二段。", encoding="utf-8")
        self.addCleanup(lambda: shutil.rmtree(d, ignore_errors=True))
        self.assertEqual(len(parse(str(f))), 2)

    def test_txt_is_normalized_to_markdown(self):
        d = pathlib.Path("data/_tests"); d.mkdir(parents=True, exist_ok=True)
        f = d / "产品说明.txt"
        f.write_text("第一段。\n\n第二段。", encoding="utf-8")
        self.addCleanup(lambda: shutil.rmtree(d, ignore_errors=True))
        markdown = to_markdown(str(f))
        self.assertTrue(markdown.startswith("# 产品说明\n\n"))
        self.assertIn("第一段。\n\n第二段。", markdown)

    def test_build_index(self):
        d = pathlib.Path("data/_tests"); d.mkdir(parents=True, exist_ok=True)
        (d / "a.md").write_text("AAA。\n\nBBB。", encoding="utf-8")
        from rag_core import InMemoryVectorStore, embed

        store = InMemoryVectorStore()
        n = build_index(RequestContext("t", "r"), str(d), store, embed)
        self.assertGreaterEqual(n, 2)
        self.addCleanup(lambda: shutil.rmtree(d, ignore_errors=True))


if __name__ == "__main__":
    unittest.main()
