"""
schema.py

Shared data types for the human-review workflow: a `ReviewRow` is one
suspicious word plus enough context (raw + corrected) for a person to
decide what to do with it, without needing the original scanned page.

Column names match the original project's
`make_review_table_with_context.py` output so existing spreadsheets /
review habits transfer directly:

    id, page, image_file, word, reason, candidates,
    corrected_context, raw_context, decision, replacement, notes
"""

from __future__ import annotations

import re
from dataclasses import dataclass

REVIEW_CSV_FIELDNAMES = [
    "id",
    "page",
    "image_file",
    "word",
    "reason",
    "candidates",
    "corrected_context",
    "raw_context",
    "decision",
    "replacement",
    "notes",
]


@dataclass
class ReviewRow:
    id: int
    page: str = ""
    image_file: str = ""
    word: str = ""
    reason: str = ""
    candidates: str = ""
    corrected_context: str = ""
    raw_context: str = ""
    decision: str = "pending"
    replacement: str = ""
    notes: str = ""

    def as_csv_dict(self) -> dict[str, str]:
        return {name: str(getattr(self, name)) for name in REVIEW_CSV_FIELDNAMES}


@dataclass
class PageSpan:
    page: str
    image_file: str
    start: int
    end: int


_PAGE_RE = re.compile(
    r"^===== Страница\s+(?P<page>\d+|номер не распознан)\s+\|\s+(?P<image>[^=]+?)\s+=====$",
    re.MULTILINE,
)

# Fallback for DOCX files using the bold-digit-marker-per-page
# convention (a paragraph containing only a number, one per page --
# see tests/golden/extract_manual_reference.py and every
# one-page-per-sheet script in this project). Bold formatting itself
# doesn't survive io/docx_reader.py's flatten-to-plain-text step, but
# the standalone digit line does; a line that is JUST digits, with
# nothing else on it, is a reliable enough marker in practice (real
# Chechen prose lines are never bare numbers).
_STANDALONE_PAGE_LINE_RE = re.compile(r"^(?P<page>\d+)$", re.MULTILINE)


def build_page_index(text: str) -> list[PageSpan]:
    """
    Builds page spans either from the "===== Страница N | file.jpg
    =====" service headers ChechenOcrProcessor.process_text() leaves
    untouched in the corrected output (see
    processor.is_protected_service_line), or -- if none of those are
    present -- from standalone-digit-only lines (the bold-marker DOCX
    convention, after flattening to plain text loses the bold info but
    keeps the line itself).
    """
    matches = list(_PAGE_RE.finditer(text))
    spans: list[PageSpan] = []

    if matches:
        for i, m in enumerate(matches):
            start = m.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            spans.append(
                PageSpan(
                    page=m.group("page"),
                    image_file=m.group("image").strip(),
                    start=start,
                    end=end,
                )
            )
        return spans

    fallback_matches = list(_STANDALONE_PAGE_LINE_RE.finditer(text))
    for i, m in enumerate(fallback_matches):
        start = m.end()  # page's content starts AFTER the marker line itself
        end = fallback_matches[i + 1].start() if i + 1 < len(fallback_matches) else len(text)
        spans.append(
            PageSpan(
                page=m.group("page"),
                image_file="",
                start=start,
                end=end,
            )
        )

    return spans


def page_for_position(spans: list[PageSpan], pos: int) -> tuple[str, str]:
    if pos < 0:
        return "", ""
    for span in spans:
        if span.start <= pos < span.end:
            return span.page, span.image_file
    return "", ""
