#!/usr/bin/env python3
"""
extract_manual_reference.py

Extracts the manually-proofread reference text from
`recognized_text_after_70_pages (1).docx` into a structured,
page-indexed plain-text file, filtered to a given page range.

A "page marker" paragraph is a paragraph whose entire (stripped) text
is a bare integer -- this matches how the manual proofreader marked
page boundaries in the DOCX (paragraph text == "11", "12", ... often
bold, but boldness is not required for detection).

Usage:
    python extract_manual_reference.py \
        --docx "recognized_text_after_70_pages (1).docx" \
        --first-page 11 --last-page 73 \
        --out golden_expected_pages_11_73.txt
"""

from __future__ import annotations

import argparse
from pathlib import Path

from docx import Document


def is_page_marker(paragraph) -> int | None:
    """
    A page marker is a paragraph whose text is a bare integer AND whose
    text is entirely bold. Requiring boldness matters: an audit of the
    full document found stray non-bold pure-digit paragraphs (likely
    footnote references or OCR noise in the less-reviewed sections
    past page ~76) that would otherwise be misread as page markers and
    silently corrupt page attribution. All genuine page markers in the
    manually-proofread range (11-73) were verified to be fully bold.
    """
    text = paragraph.text.strip()
    if not text.isdigit():
        return None

    runs = paragraph.runs
    if not runs:
        return None
    if not all(run.bold for run in runs):
        return None

    return int(text)


def extract_pages(docx_path: Path) -> dict[int, list[str]]:
    """Returns {page_number: [line, line, ...]} for every page found."""
    document = Document(str(docx_path))

    pages: dict[int, list[str]] = {}
    current_page: int | None = None

    for paragraph in document.paragraphs:
        text = paragraph.text
        page_num = is_page_marker(paragraph)

        if page_num is not None:
            current_page = page_num
            pages.setdefault(current_page, [])
            continue

        if current_page is None:
            # Content before the first page marker (title page, etc.) -- skip.
            continue

        pages[current_page].append(text)

    return pages


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--docx", required=True, type=Path)
    parser.add_argument("--first-page", required=True, type=int)
    parser.add_argument("--last-page", required=True, type=int)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    pages = extract_pages(args.docx)

    all_page_nums = sorted(pages.keys())
    in_range = [p for p in all_page_nums if args.first_page <= p <= args.last_page]
    missing = [p for p in range(args.first_page, args.last_page + 1) if p not in pages]

    lines_out: list[str] = []
    for page_num in in_range:
        lines_out.append(f"===== PAGE {page_num} =====")
        lines_out.extend(pages[page_num])
        lines_out.append("")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines_out), encoding="utf-8")

    print(
        f"Pages found in DOCX overall: {len(all_page_nums)} "
        f"(range {all_page_nums[0]}-{all_page_nums[-1]})"
    )
    print(
        f"Pages extracted in requested range [{args.first_page}-{args.last_page}]: {len(in_range)}"
    )
    print(f"Missing page numbers in requested range: {missing or 'none'}")
    print(f"Written to: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
