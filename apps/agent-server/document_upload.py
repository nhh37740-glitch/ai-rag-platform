from __future__ import annotations

import asyncio
from pathlib import Path
import tempfile
import uuid

from fastapi import UploadFile
from ingestion import SUPPORTED_EXTENSIONS, to_markdown

MAX_UPLOAD_BYTES = 25 * 1024 * 1024


class UploadValidationError(ValueError):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


async def convert_uploaded_documents(files: list[UploadFile]) -> list[tuple[str, str]]:
    """Validate uploads and return (original filename, Markdown) pairs."""
    if not files:
        raise UploadValidationError(400, "至少选择一个文件")

    converted = []
    with tempfile.TemporaryDirectory(prefix="dev-knowledge-upload-") as temporary_dir:
        temporary_root = Path(temporary_dir)
        for upload in files:
            original_name = Path(upload.filename or "document").name
            extension = Path(original_name).suffix.lower()
            if extension not in SUPPORTED_EXTENSIONS:
                supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
                raise UploadValidationError(415, f"{original_name}: 仅支持 {supported}")

            content = await upload.read(MAX_UPLOAD_BYTES + 1)
            await upload.close()
            if len(content) > MAX_UPLOAD_BYTES:
                raise UploadValidationError(413, f"{original_name}: 文件不能超过 25 MB")

            temporary_source = temporary_root / f"source-{uuid.uuid4().hex}{extension}"
            temporary_source.write_bytes(content)
            try:
                markdown = await asyncio.to_thread(
                    to_markdown,
                    str(temporary_source),
                    Path(original_name).stem,
                )
            except (OSError, RuntimeError, ValueError) as exc:
                raise UploadValidationError(422, f"{original_name}: {exc}") from exc
            converted.append((original_name, markdown))
    return converted


__all__ = [
    "MAX_UPLOAD_BYTES",
    "SUPPORTED_EXTENSIONS",
    "UploadValidationError",
    "convert_uploaded_documents",
]
