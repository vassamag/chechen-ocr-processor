#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
extract_remaining_suspicious_contexts.py

Diagnostic script for the OCR processor.

It does NOT modify the text.
It extracts contexts around remaining suspicious characters in the final TXT:
    ] | ! Ї ї І і [ 1

Default focus is:
    ] | ! Ї

The report helps decide whether these are real OCR errors, harmless punctuation,
technical artifacts, or cases that should wait for manual page verification.
"""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path
from typing import Dict, List, Tuple


DEFAULT_CHARS = ["]", "|", "!", "Ї"]


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def clean_context(s: str) -> str:
    """Make context readable on one line."""
    s = s.replace("\r", "\n")
    s = re.sub(r"\n+", " ⏎ ", s)
    s = re.sub(r"[ \t]+", " ", s)
    return s.strip()


def estimate_page(text_before: str) -> str:
    """
    Best-effort page detection.

    Looks backward for common page markers like:
      Page 123
      Страница 123
      --- PAGE 123 ---
      image_file: IMG...
    If no marker is found, returns empty string.
    """
    tail = text_before[-5000:]

    patterns = [
        r"(?i)\bpage\s*[:#-]?\s*(\d{1,4})\b",
        r"(?i)\bстраница\s*[:#-]?\s*(\d{1,4})\b",
        r"(?i)\bстр\.?\s*[:#-]?\s*(\d{1,4})\b",
        r"[-= ]{2,}\s*(\d{1,4})\s*[-= ]{2,}",
        r"\n\s*(\d{1,4})\s*\n",
    ]

    for pat in patterns:
        matches = list(re.finditer(pat, tail))
        if matches:
            return matches[-1].group(1)

    return ""


def line_col_from_pos(text: str, pos: int) -> Tuple[int, int]:
    line = text.count("\n", 0, pos) + 1
    last_nl = text.rfind("\n", 0, pos)
    col = pos + 1 if last_nl < 0 else pos - last_nl
    return line, col


def collect_occurrences(text: str, chars: List[str], radius: int, max_per_char: int) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []

    for ch in chars:
        count_for_char = 0
        start = 0

        while True:
            pos = text.find(ch, start)
            if pos < 0:
                break

            count_for_char += 1

            if max_per_char <= 0 or count_for_char <= max_per_char:
                left = max(0, pos - radius)
                right = min(len(text), pos + len(ch) + radius)
                line, col = line_col_from_pos(text, pos)
                page = estimate_page(text[:pos])

                rows.append({
                    "char": ch,
                    "occurrence_no_for_char": str(count_for_char),
                    "absolute_pos": str(pos),
                    "line": str(line),
                    "column": str(col),
                    "estimated_page": page,
                    "context": clean_context(text[left:right]),
                })

            start = pos + len(ch)

    return rows


def char_counts(text: str, chars: List[str]) -> Dict[str, int]:
    return {ch: text.count(ch) for ch in chars}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, help="Final TXT file to inspect")
    parser.add_argument("--out", required=True, help="TXT report path")
    parser.add_argument("--csv", default="", help="Optional CSV output path")
    parser.add_argument(
        "--chars",
        default="".join(DEFAULT_CHARS),
        help="Characters to extract. Example: \"]|!Ї[\". Default: ]|!Ї",
    )
    parser.add_argument(
        "--radius",
        type=int,
        default=90,
        help="Number of characters before/after suspicious symbol in context. Default: 90",
    )
    parser.add_argument(
        "--max-per-char",
        type=int,
        default=300,
        help="Maximum contexts to include per character. Use 0 for unlimited. Default: 300",
    )
    args = parser.parse_args()

    source_path = Path(args.source)
    out_path = Path(args.out)
    csv_path = Path(args.csv) if args.csv else out_path.with_suffix(".csv")

    if not source_path.exists():
        raise SystemExit(f"Source not found: {source_path}")

    chars = []
    for ch in args.chars:
        if ch not in chars:
            chars.append(ch)

    text = read_text(source_path)
    counts = char_counts(text, chars)
    rows = collect_occurrences(text, chars, args.radius, args.max_per_char)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    lines: List[str] = []
    lines.append("extract_remaining_suspicious_contexts.py report")
    lines.append("")
    lines.append(f"Source: {source_path}")
    lines.append(f"CSV: {csv_path}")
    lines.append(f"Characters checked: {' '.join(repr(c) for c in chars)}")
    lines.append(f"Context radius: {args.radius}")
    lines.append(f"Max per char in report: {args.max_per_char}")
    lines.append("")
    lines.append("Counts:")
    for ch in chars:
        lines.append(f"  {repr(ch)}: {counts[ch]}")

    lines.append("")
    lines.append("Contexts:")
    lines.append("")

    current_char = None
    for row in rows:
        if row["char"] != current_char:
            current_char = row["char"]
            lines.append("")
            lines.append("=" * 80)
            lines.append(f"CHAR {repr(current_char)}")
            lines.append("=" * 80)

        lines.append(
            f"[{row['char']} #{row['occurrence_no_for_char']}] "
            f"line={row['line']} col={row['column']} "
            f"pos={row['absolute_pos']} page~={row['estimated_page']}"
        )
        lines.append(row["context"])
        lines.append("")

    if not rows:
        lines.append("No occurrences found.")

    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        fieldnames = [
            "char",
            "occurrence_no_for_char",
            "absolute_pos",
            "line",
            "column",
            "estimated_page",
            "context",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    print(f"Report: {out_path}")
    print(f"CSV: {csv_path}")
    print(f"Counts: {counts}")
    print(f"Rows written: {len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
