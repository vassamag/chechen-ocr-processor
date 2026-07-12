"""
docx_writer.py

Writes corrected text to a DOCX file, optionally highlighting
suspicious words in yellow so a reviewer can spot them visually
without needing the CSV review table open side by side.

Ported from src/process.py::add_text_with_highlights / save_docx.
"""

from __future__ import annotations

import re
from pathlib import Path

from docx import Document
from docx.document import Document as DocumentObject
from docx.enum.text import WD_COLOR_INDEX

_TOKEN_PATTERN = re.compile(r"([А-Яа-яЁёӀA-Za-z0-9ІіЇїЈј\[\]\|!\-]+|\s+|.)", flags=re.UNICODE)
_STRIP_CHARS = ".,!?;:()[]{}«»\"'“”„"


def _add_text_with_highlights(
    document: DocumentObject, text: str, suspicious_words: set[str]
) -> None:
    for paragraph_text in text.split("\n"):
        paragraph = document.add_paragraph()
        for token in _TOKEN_PATTERN.findall(paragraph_text):
            run = paragraph.add_run(token)
            clean = token.strip(_STRIP_CHARS)
            if clean in suspicious_words:
                run.font.highlight_color = WD_COLOR_INDEX.YELLOW


def save_docx(
    text: str,
    path: Path,
    suspicious_words: list[str] | None = None,
) -> None:
    """
    Writes `text` to a new DOCX at `path`, one paragraph per line.
    If `suspicious_words` is given, any token in the text matching one
    of those words (after stripping surrounding punctuation) is
    highlighted in yellow.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    document = Document()

    if suspicious_words:
        _add_text_with_highlights(document, text, set(suspicious_words))
    else:
        for paragraph_text in text.split("\n"):
            document.add_paragraph(paragraph_text)

    document.save(str(path))
