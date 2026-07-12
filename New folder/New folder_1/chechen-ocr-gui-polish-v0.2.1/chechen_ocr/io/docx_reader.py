"""
docx_reader.py

Extracts plain paragraph (+ simple table) text from a DOCX file, for
feeding into ChechenOcrProcessor.process_text() when the OCR output
was delivered as a DOCX instead of a raw TXT dump.

Ported from src/run_pipeline.py::extract_docx_to_txt. This is
intentionally a plain-text extraction (no formatting preserved) --
matching the original tool's stated behavior for this first DOCX
input path.

A DOCX is a ZIP archive, so before handing it to python-docx (which
will decompress it unconditionally), check_docx_zip_safety() screens
for zip-bomb signatures -- see security.py for what that covers.
"""

from __future__ import annotations

from pathlib import Path

from docx import Document

from ..config import Settings
from ..security import check_docx_zip_safety, check_file_size


def extract_docx_to_text(docx_path: Path, settings: Settings | None = None) -> str:
    settings = settings or Settings.default()
    docx_path = Path(docx_path)

    check_file_size(docx_path, settings.max_docx_file_size_bytes, label="DOCX")
    check_docx_zip_safety(
        docx_path,
        max_uncompressed_bytes=settings.max_docx_uncompressed_size_bytes,
        max_compression_ratio=settings.max_docx_compression_ratio,
        max_entry_count=settings.max_docx_zip_entry_count,
    )

    document = Document(str(docx_path))

    lines: list[str] = []
    for paragraph in document.paragraphs:
        lines.append(paragraph.text)

    for table in document.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells]
            if any(cells):
                lines.append("\t".join(cells))

    return "\n".join(lines)
