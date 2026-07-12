#!/usr/bin/env python3
"""
parse_raw_ocr.py

Parses the raw (pre-correction) OCR dump into page-indexed blocks,
using the "===== Страница N | <filename> =====" markers produced by
the original scanning/OCR batch process.

IMPORTANT data-quality note discovered while building this harness:
a handful of page numbers appeared MORE THAN ONCE in the raw dump
within the 11-73 range. Most turned out to be genuine duplicate/retake
photos of the same page (21, 27, 32, 69) -- see
manual_resolutions.PREFERRED_BLOCK_FOR_TRUE_DUPLICATE. Two others (19,
31) turned out to be a genuinely different page's photo that had been
misread as sharing that page number; manual_resolutions.
PAGE_NUMBER_OVERRIDES reassigns those to their true page (24 and 33
respectively, confirmed against the original scan photos), after
which 19 and 31 each resolve to exactly one block again.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_PAGE_MARKER_RE = re.compile(
    r"^===== Страница (?P<page>\d+|номер не распознан) \| (?P<filename>.+?) =====$"
)


@dataclass
class RawPageBlock:
    page: int | None  # None for "номер не распознан"
    filename: str
    text: str


def parse_raw_ocr(raw_text: str) -> list[RawPageBlock]:
    lines = raw_text.splitlines()
    blocks: list[RawPageBlock] = []

    current_page: int | None = None
    current_filename: str = ""
    current_lines: list[str] = []

    def flush():
        if current_filename:
            blocks.append(
                RawPageBlock(
                    page=current_page,
                    filename=current_filename,
                    text="\n".join(current_lines).strip("\n"),
                )
            )

    for line in lines:
        match = _PAGE_MARKER_RE.match(line.strip())
        if match:
            flush()
            page_str = match.group("page")
            current_page = int(page_str) if page_str.isdigit() else None
            current_filename = match.group("filename")
            current_lines = []
        else:
            current_lines.append(line)

    flush()
    return blocks


def group_by_page(blocks: list[RawPageBlock]) -> dict[int, list[RawPageBlock]]:
    """
    Groups blocks by page number, applying the hand-verified
    manual_resolutions.py table:

    1. PAGE_NUMBER_OVERRIDES reassigns a block's page number by
       filename, regardless of what was originally parsed (whether
       that was None -- "номер не распознан" -- or a wrong number
       shared with some unrelated page).
    2. Any page that still has more than one block afterwards is
       resolved via PREFERRED_BLOCK_FOR_TRUE_DUPLICATE (true
       duplicate/retake photos, or one verified block plus one
       still-unidentified stray -- see that table's comments).
    """
    from .manual_resolutions import PAGE_NUMBER_OVERRIDES, PREFERRED_BLOCK_FOR_TRUE_DUPLICATE

    grouped: dict[int, list[RawPageBlock]] = {}
    for block in blocks:
        page = PAGE_NUMBER_OVERRIDES.get(block.filename, block.page)
        if page is None:
            continue
        grouped.setdefault(page, []).append(block)

    for page, filename in PREFERRED_BLOCK_FOR_TRUE_DUPLICATE.items():
        if page in grouped and len(grouped[page]) > 1:
            grouped[page] = [b for b in grouped[page] if b.filename == filename]

    return grouped


def pages_in_range(
    blocks: list[RawPageBlock], first_page: int, last_page: int
) -> dict[int, list[RawPageBlock]]:
    grouped = group_by_page(blocks)
    return {p: v for p, v in grouped.items() if first_page <= p <= last_page}


if __name__ == "__main__":
    import sys

    path = Path(sys.argv[1])
    blocks = parse_raw_ocr(path.read_text(encoding="utf-8", errors="replace"))
    grouped = pages_in_range(blocks, 11, 73)

    duplicates = {p: v for p, v in grouped.items() if len(v) > 1}
    print(f"Pages in range with content: {len(grouped)}")
    print(f"Pages with MULTIPLE raw blocks (data-quality flag): {sorted(duplicates)}")
    for p in sorted(duplicates):
        for b in duplicates[p]:
            print(f"  page {p}: {b.filename} ({len(b.text)} chars)")
