#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
apply_review_table.py

Safely applies approved replacements from a review CSV to a corrected OCR text.

Default safety policy:
- applies only rows where decision == "replace" and replacement is not empty;
- does NOT apply reject/pending rows;
- prefers context-based replacement using corrected_context;
- does NOT perform global word replacement unless --allow-word-fallback is supplied;
- writes a detailed report and an optional applied/skipped CSV log.
"""
from __future__ import annotations

import argparse
import csv
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

WORD_CHARS = r"A-Za-zА-Яа-яЁёІіЇїӀӏ0-9_"

@dataclass
class ApplyResult:
    row_id: str
    page: str
    word: str
    replacement: str
    status: str
    detail: str

def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")

def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")

def normalize_space(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()

def token_pattern(token: str) -> re.Pattern:
    escaped = re.escape(token)
    return re.compile(rf"(?<![{WORD_CHARS}]){escaped}(?![{WORD_CHARS}])")

def replace_once_in_span(text: str, start: int, end: int, word: str, replacement: str) -> Tuple[str, bool, str]:
    span = text[start:end]
    pat = token_pattern(word)
    m = pat.search(span)
    if not m:
        pos = span.find(word)
        if pos < 0:
            return text, False, "word_not_found_inside_context"
        abs_start = start + pos
        abs_end = abs_start + len(word)
    else:
        abs_start = start + m.start()
        abs_end = start + m.end()
    return text[:abs_start] + replacement + text[abs_end:], True, "applied_context"

def apply_row_context(text: str, row: Dict[str, str]) -> Tuple[str, ApplyResult]:
    row_id = row.get("id", "")
    page = row.get("page", "")
    word = (row.get("word") or "").strip()
    replacement = (row.get("replacement") or "").strip()
    context = row.get("corrected_context") or ""
    if not word:
        return text, ApplyResult(row_id, page, word, replacement, "skipped", "empty_word")
    if not replacement:
        return text, ApplyResult(row_id, page, word, replacement, "skipped", "empty_replacement")
    if word == replacement:
        return text, ApplyResult(row_id, page, word, replacement, "skipped", "word_equals_replacement")
    context_exact = context.strip()
    if context_exact:
        pos = text.find(context_exact)
        if pos >= 0:
            new_text, ok, detail = replace_once_in_span(text, pos, pos + len(context_exact), word, replacement)
            if ok:
                return new_text, ApplyResult(row_id, page, word, replacement, "applied", detail)
            return text, ApplyResult(row_id, page, word, replacement, "skipped", detail)
        if normalize_space(context_exact) and normalize_space(context_exact) in normalize_space(text):
            return text, ApplyResult(row_id, page, word, replacement, "skipped", "context_found_only_after_space_normalization")
        return text, ApplyResult(row_id, page, word, replacement, "skipped", "context_not_found")
    return text, ApplyResult(row_id, page, word, replacement, "skipped", "empty_corrected_context")

def apply_row_word_fallback(text: str, row: Dict[str, str]) -> Tuple[str, ApplyResult]:
    row_id = row.get("id", "")
    page = row.get("page", "")
    word = (row.get("word") or "").strip()
    replacement = (row.get("replacement") or "").strip()
    if not word or not replacement or word == replacement:
        return text, ApplyResult(row_id, page, word, replacement, "skipped", "fallback_invalid_row")
    matches = list(token_pattern(word).finditer(text))
    if len(matches) == 0:
        return text, ApplyResult(row_id, page, word, replacement, "skipped", "fallback_word_not_found")
    if len(matches) > 1:
        return text, ApplyResult(row_id, page, word, replacement, "skipped", f"fallback_ambiguous_{len(matches)}_matches")
    m = matches[0]
    return text[:m.start()] + replacement + text[m.end():], ApplyResult(row_id, page, word, replacement, "applied", "applied_unique_word_fallback")

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--review", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--log-csv", default="")
    parser.add_argument("--allow-word-fallback", action="store_true")
    args = parser.parse_args()
    source_path = Path(args.source)
    review_path = Path(args.review)
    out_path = Path(args.out)
    report_path = Path(args.report)
    log_csv_path = Path(args.log_csv) if args.log_csv else report_path.with_suffix(".csv")
    if not source_path.exists():
        raise SystemExit(f"Source not found: {source_path}")
    if not review_path.exists():
        raise SystemExit(f"Review CSV not found: {review_path}")
    text = read_text(source_path)
    with review_path.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    results: List[ApplyResult] = []
    considered = 0
    for row in rows:
        decision = (row.get("decision") or "").strip().lower()
        replacement = (row.get("replacement") or "").strip()
        if decision != "replace":
            results.append(ApplyResult(row.get("id", ""), row.get("page", ""), row.get("word", ""), replacement, "not_considered", f"decision={decision or 'empty'}"))
            continue
        if not replacement:
            results.append(ApplyResult(row.get("id", ""), row.get("page", ""), row.get("word", ""), replacement, "skipped", "replace_with_empty_replacement"))
            continue
        considered += 1
        before = text
        text, res = apply_row_context(text, row)
        if res.status != "applied" and args.allow_word_fallback:
            fallback_text, fallback_res = apply_row_word_fallback(before, row)
            if fallback_res.status == "applied":
                text, res = fallback_text, fallback_res
            else:
                text = before
        results.append(res)
    write_text(out_path, text)
    log_csv_path.parent.mkdir(parents=True, exist_ok=True)
    with log_csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["row_id", "page", "word", "replacement", "status", "detail"])
        writer.writeheader()
        for r in results:
            writer.writerow(r.__dict__)
    counts: Dict[str, int] = {}
    detail_counts: Dict[str, int] = {}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
        detail_counts[r.detail] = detail_counts.get(r.detail, 0) + 1
    report_lines = [
        "apply_review_table.py report", "",
        f"Source: {source_path}", f"Review CSV: {review_path}", f"Output: {out_path}", f"Log CSV: {log_csv_path}", "",
        f"Rows total: {len(rows)}", f"Replace rows considered: {considered}", "", "Status counts:",
    ]
    for k in sorted(counts):
        report_lines.append(f"  {k}: {counts[k]}")
    report_lines += ["", "Detail counts:"]
    for k in sorted(detail_counts):
        report_lines.append(f"  {k}: {detail_counts[k]}")
    report_lines += ["", "Safety note:", "  reject/pending rows were not applied.", "  By default, replacements are context-based only."]
    report_lines.append("  Unique whole-token fallback was ENABLED." if args.allow_word_fallback else "  Unique whole-token fallback was DISABLED.")
    write_text(report_path, "\n".join(report_lines) + "\n")
    print(f"Created: {out_path}")
    print(f"Report: {report_path}")
    print(f"Log CSV: {log_csv_path}")
    print(f"Rows total: {len(rows)}")
    print(f"Replace rows considered: {considered}")
    print(f"Status counts: {counts}")
    print(f"Detail counts: {detail_counts}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
