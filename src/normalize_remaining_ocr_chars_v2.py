#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
normalize_remaining_ocr_chars.py

v2: cautious final normalization pass for remaining OCR artifacts.

It modifies only narrow, high-confidence cases:

1) Ї / ї -> Ӏ inside Cyrillic/Chechen words.

2) ! -> Ӏ only when it is likely a damaged palochka, not normal punctuation:
   - between Cyrillic/Chechen letters: х!окху -> хӀокху, т!аьхьа -> тӀаьхьа
   - before a Cyrillic letter inside a word, even if the previous character is an OCR Latin letter:
       Д!адахнарш-м -> ДӀадахнарш-м
   - at the end of a small whitelist of common palochka-final words:
       йо! -> йоӀ
       не! -> неӀ
       барх! -> бархӀ
       мостаг! -> мостагӀ
       доттаг! -> доттагӀ

   It does NOT touch normal punctuation such as:
       Марша вогӀийла!
       Хьо!
       Баркалла!

3) ] is removed only in clearly suspicious OCR positions:
   - inside/adjacent to Cyrillic context;
   - after a digit when adjacent to Cyrillic context;
   - isolated in Cyrillic/OCR context.

4) | is NOT modified. It is used in page headers:
       ===== Страница 11 | IMG-...jpg =====

Outputs:
- normalized TXT
- plain-text report
- CSV log with every change
"""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path
from typing import Dict, List, Tuple


CYR = "А-Яа-яЁёІіЇїӀӏ"
LAT = "A-Za-z"
TOKEN_CHARS = CYR + LAT + "0-9_\\-'"
FINAL_PALOCHKA_STEMS = {
    "йо", "ио",
    "не",
    "барх",
    "мостаг", "моста",
    "доттаг",
    "хорт",
    "бурт",
}


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def is_cyr(ch: str) -> bool:
    return bool(ch) and re.match(rf"[{CYR}]", ch) is not None


def is_token_char(ch: str) -> bool:
    return bool(ch) and re.match(rf"[{TOKEN_CHARS}]", ch) is not None


def has_cyr(s: str) -> bool:
    return re.search(rf"[{CYR}]", s) is not None


def line_col_from_pos(text: str, pos: int) -> Tuple[int, int]:
    line = text.count("\n", 0, pos) + 1
    last_nl = text.rfind("\n", 0, pos)
    col = pos + 1 if last_nl < 0 else pos - last_nl
    return line, col


def context(text: str, pos: int, radius: int = 70) -> str:
    left = max(0, pos - radius)
    right = min(len(text), pos + radius)
    s = text[left:right].replace("\r", "\n")
    s = re.sub(r"\n+", " ⏎ ", s)
    s = re.sub(r"[ \t]+", " ", s)
    return s.strip()


def add_log(log: List[Dict[str, str]], text_before: str, pos: int, old: str, new: str, rule: str) -> None:
    line, col = line_col_from_pos(text_before, pos)
    log.append({
        "rule": rule,
        "old": old,
        "new": new,
        "absolute_pos_before_change": str(pos),
        "line_before_change": str(line),
        "column_before_change": str(col),
        "context_before_change": context(text_before, pos),
    })


def token_bounds(text: str, pos: int) -> Tuple[int, int]:
    start = pos
    while start > 0 and is_token_char(text[start - 1]):
        start -= 1
    end = pos + 1
    while end < len(text) and is_token_char(text[end]):
        end += 1
    return start, end


def should_replace_bang(text: str, pos: int) -> Tuple[bool, str]:
    prev_ch = text[pos - 1] if pos > 0 else ""
    next_ch = text[pos + 1] if pos + 1 < len(text) else ""

    start, end = token_bounds(text, pos)
    token = text[start:end]
    before = token[:pos - start]
    after = token[pos - start + 1:]

    # Strongest case: inside a Cyrillic word.
    if is_cyr(prev_ch) and is_cyr(next_ch):
        return True, "bang_between_cyrillic_letters"

    # Common OCR case: Latin/other letter before !, Cyrillic after !.
    # Example: Д!адахнарш-м, х!окху where previous may be OCR-damaged.
    if next_ch and is_cyr(next_ch) and before and not before.endswith((" ", "\n", "\t")):
        if has_cyr(before) or re.search(r"[A-Za-z]$", before):
            return True, "bang_before_cyrillic_inside_token"

    # ! at beginning of token before Cyrillic: !итта -> Ӏитта
    if not before and is_cyr(next_ch):
        return True, "bang_initial_before_cyrillic"

    # End-of-token palochka cases. Must be whitelisted to avoid corrupting punctuation.
    if before and not after and is_cyr(prev_ch):
        stem = before.lower().replace("Ӏ", "Ӏ")
        stem = stem.strip("-'")
        if stem in FINAL_PALOCHKA_STEMS:
            return True, "bang_final_known_palochka_word"

    return False, ""


def normalize_palochka_variants(text: str, log: List[Dict[str, str]]) -> str:
    chars = list(text)
    for i, ch in enumerate(chars):
        if ch in ("Ї", "ї"):
            start, end = token_bounds(text, i)
            token = text[start:end]
            if has_cyr(token):
                add_log(log, text, i, ch, "Ӏ", "yi_variant_inside_cyrillic_token")
                chars[i] = "Ӏ"

    # Rebuild after Ї/ї changes before processing !
    intermediate = "".join(chars)
    chars = list(intermediate)

    for i, ch in enumerate(chars):
        if ch != "!":
            continue
        ok, rule = should_replace_bang(intermediate, i)
        if ok:
            add_log(log, intermediate, i, "!", "Ӏ", rule)
            chars[i] = "Ӏ"

    return "".join(chars)


def remove_bracket_noise(text: str, log: List[Dict[str, str]]) -> str:
    chars = list(text)
    remove_positions = set()

    for i, ch in enumerate(chars):
        if ch != "]":
            continue

        prev_ch = chars[i - 1] if i > 0 else ""
        next_ch = chars[i + 1] if i + 1 < len(chars) else ""

        near_left = text[max(0, i - 25):i]
        near_right = text[i + 1:min(len(text), i + 26)]
        near = near_left + near_right

        should_remove = False
        reason = ""

        if is_cyr(prev_ch) or is_cyr(next_ch):
            should_remove = True
            reason = "right_bracket_adjacent_to_cyrillic"
        elif prev_ch.isdigit() and has_cyr(near_right):
            should_remove = True
            reason = "right_bracket_after_digit_near_cyrillic"
        elif has_cyr(near) and (not prev_ch or prev_ch.isspace()) and (not next_ch or next_ch.isspace()):
            should_remove = True
            reason = "isolated_right_bracket_in_cyrillic_context"
        elif prev_ch in "-=—–" and has_cyr(near):
            should_remove = True
            reason = "right_bracket_after_dash_or_equals_in_cyrillic_context"

        if should_remove:
            remove_positions.add(i)
            add_log(log, text, i, "]", "", reason)

    if not remove_positions:
        return text

    return "".join(ch for i, ch in enumerate(chars) if i not in remove_positions)


def count_bang_inside_cyrillic_candidates(text: str) -> int:
    count = 0
    for i, ch in enumerate(text):
        if ch == "!":
            ok, _ = should_replace_bang(text, i)
            if ok:
                count += 1
    return count


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, help="Input final TXT")
    parser.add_argument("--out", required=True, help="Output normalized TXT")
    parser.add_argument("--report", required=True, help="Plain-text report path")
    parser.add_argument("--log-csv", default="", help="Optional CSV log path")
    args = parser.parse_args()

    source_path = Path(args.source)
    out_path = Path(args.out)
    report_path = Path(args.report)
    log_csv_path = Path(args.log_csv) if args.log_csv else report_path.with_suffix(".csv")

    if not source_path.exists():
        raise SystemExit(f"Source not found: {source_path}")

    original = read_text(source_path)
    log: List[Dict[str, str]] = []

    text = original
    text = normalize_palochka_variants(text, log)
    text = remove_bracket_noise(text, log)

    write_text(out_path, text)

    log_csv_path.parent.mkdir(parents=True, exist_ok=True)
    with log_csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        fieldnames = [
            "rule",
            "old",
            "new",
            "absolute_pos_before_change",
            "line_before_change",
            "column_before_change",
            "context_before_change",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in log:
            writer.writerow(row)

    rule_counts: Dict[str, int] = {}
    for row in log:
        rule_counts[row["rule"]] = rule_counts.get(row["rule"], 0) + 1

    before_counts = {
        "]": original.count("]"),
        "!": original.count("!"),
        "Ї": original.count("Ї"),
        "ї": original.count("ї"),
        "Ӏ": original.count("Ӏ"),
        "bang_candidates_by_rule": count_bang_inside_cyrillic_candidates(original),
    }
    after_counts = {
        "]": text.count("]"),
        "!": text.count("!"),
        "Ї": text.count("Ї"),
        "ї": text.count("ї"),
        "Ӏ": text.count("Ӏ"),
        "bang_candidates_by_rule": count_bang_inside_cyrillic_candidates(text),
    }

    lines: List[str] = []
    lines.append("normalize_remaining_ocr_chars.py v2 report")
    lines.append("")
    lines.append(f"Source: {source_path}")
    lines.append(f"Output: {out_path}")
    lines.append(f"CSV log: {log_csv_path}")
    lines.append("")
    lines.append("Before counts:")
    for k, v in before_counts.items():
        lines.append(f"  {repr(k)}: {v}")
    lines.append("")
    lines.append("After counts:")
    for k, v in after_counts.items():
        lines.append(f"  {repr(k)}: {v}")
    lines.append("")
    lines.append("Rule counts:")
    for k in sorted(rule_counts):
        lines.append(f"  {k}: {rule_counts[k]}")
    lines.append("")
    lines.append("First 150 changes:")
    for row in log[:150]:
        lines.append(
            f"  {row['rule']}: {row['old']} -> {row['new']} "
            f"(line {row['line_before_change']}, col {row['column_before_change']})"
        )
        lines.append(f"    {row['context_before_change']}")
    if len(log) > 150:
        lines.append(f"  ... {len(log) - 150} more changes in CSV log")

    lines.append("")
    lines.append("Safety notes:")
    lines.append("  | was not modified.")
    lines.append("  ! punctuation was not globally changed.")
    lines.append("  ! was changed only when likely a damaged palochka.")
    lines.append("  Ї/ї were changed only inside Cyrillic tokens.")
    lines.append("  ] was removed only in high-confidence OCR-noise contexts.")

    write_text(report_path, "\n".join(lines) + "\n")

    print(f"Created: {out_path}")
    print(f"Report: {report_path}")
    print(f"Log CSV: {log_csv_path}")
    print(f"Before counts: {before_counts}")
    print(f"After counts: {after_counts}")
    print(f"Rule counts: {rule_counts}")
    print(f"Changes: {len(log)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
