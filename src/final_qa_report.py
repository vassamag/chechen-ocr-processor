#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
final_qa_report.py

Creates a compact QA report for the current OCR processor output.
"""
from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path
from typing import Dict, List

CYRILLIC_WITH_LATIN_I_RE = re.compile(r"[А-Яа-яЁёІіЇїӀӏA-Za-z\-']*?[А-Яа-яЁёІіЇїӀӏ][А-Яа-яЁёІіЇїӀӏA-Za-z\-']*I[А-Яа-яЁёІіЇїӀӏA-Za-z\-']*")
SUSPICIOUS_CHARS = ["[", "]", "|", "!", "Ї", "ї", "І", "і"]

def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")

def count_review(review_path: Path) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    if not review_path or not review_path.exists():
        return counts
    with review_path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            d = (row.get("decision") or "empty").strip().lower() or "empty"
            counts[d] = counts.get(d, 0) + 1
    return counts

def pending_examples(review_path: Path, limit: int = 30) -> List[str]:
    out: List[str] = []
    if not review_path or not review_path.exists():
        return out
    with review_path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if (row.get("decision") or "").strip().lower() == "pending":
                out.append(f"id={row.get('id','')} page={row.get('page','')} word={row.get('word','')} reason={row.get('reason','')}")
                if len(out) >= limit:
                    break
    return out

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--final", required=True)
    parser.add_argument("--review", default="")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    final_path = Path(args.final)
    review_path = Path(args.review) if args.review else None
    out_path = Path(args.out)
    if not final_path.exists():
        raise SystemExit(f"Final text not found: {final_path}")
    text = read_text(final_path)
    review_counts = count_review(review_path) if review_path else {}
    pending = pending_examples(review_path) if review_path else []
    latin_i_cyr_words = CYRILLIC_WITH_LATIN_I_RE.findall(text)
    unique_latin_i_cyr = sorted(set(latin_i_cyr_words))[:100]
    lines = [
        "final_qa_report.py", "", f"Final TXT: {final_path}", f"Review CSV: {review_path if review_path else '(not provided)'}", "",
        "Text stats:", f"  characters: {len(text)}", f"  lines: {text.count(chr(10)) + 1}", f"  palochka_U+04C0_count: {text.count('Ӏ')}", f"  latin_I_count_total: {text.count('I')}", f"  latin_I_inside_cyrillic_word_count: {len(latin_i_cyr_words)}", "",
        "Suspicious character counts:",
    ]
    for ch in SUSPICIOUS_CHARS:
        lines.append(f"  {repr(ch)}: {text.count(ch)}")
    if review_counts:
        lines += ["", "Review decision counts:"]
        for k in sorted(review_counts):
            lines.append(f"  {k}: {review_counts[k]}")
    if pending:
        lines += ["", "Pending review examples:"]
        for item in pending:
            lines.append(f"  {item}")
    lines += ["", "Examples of remaining Latin I inside Cyrillic words:"]
    if unique_latin_i_cyr:
        for w in unique_latin_i_cyr:
            lines.append(f"  {w}")
    else:
        lines.append("  none")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Report: {out_path}")
    print(f"latin_I_inside_cyrillic_word_count: {len(latin_i_cyr_words)}")
    print(f"palochka_U+04C0_count: {text.count('Ӏ')}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
