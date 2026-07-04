#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
normalize_palochka_final.py

Safely normalizes temporary Latin capital I (U+0049) to Chechen palochka Ӏ (U+04C0)
inside Cyrillic/Chechen words only.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Dict, List, Tuple

CYRILLIC_RE = re.compile(r"[А-Яа-яЁёІіЇїӀӏ]")
TOKEN_RE = re.compile(r"[A-Za-zА-Яа-яЁёІіЇїӀӏ][A-Za-zА-Яа-яЁёІіЇїӀӏ\-']*")
ROMAN_RE = re.compile(r"^[IVXLCDM]+$", re.IGNORECASE)

def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")

def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")

def should_normalize_token(token: str) -> bool:
    if "I" not in token:
        return False
    if not CYRILLIC_RE.search(token):
        return False
    if token.startswith("I-"):
        return False
    if ROMAN_RE.fullmatch(token):
        return False
    return True

def normalize_text(text: str) -> Tuple[str, Dict[str, int], List[Tuple[str, str]]]:
    counts = {"tokens_seen": 0, "tokens_changed": 0, "latin_I_replaced": 0, "tokens_skipped_I_hyphen": 0, "tokens_skipped_ascii_or_roman": 0}
    examples: List[Tuple[str, str]] = []
    def repl(match: re.Match) -> str:
        token = match.group(0)
        counts["tokens_seen"] += 1
        if "I" not in token:
            return token
        if token.startswith("I-"):
            counts["tokens_skipped_I_hyphen"] += 1
            return token
        if not CYRILLIC_RE.search(token) or ROMAN_RE.fullmatch(token):
            counts["tokens_skipped_ascii_or_roman"] += 1
            return token
        if should_normalize_token(token):
            new = token.replace("I", "Ӏ")
            if new != token:
                counts["tokens_changed"] += 1
                counts["latin_I_replaced"] += token.count("I")
                if len(examples) < 100:
                    examples.append((token, new))
            return new
        return token
    return TOKEN_RE.sub(repl, text), counts, examples

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    source_path = Path(args.source)
    out_path = Path(args.out)
    report_path = Path(args.report)
    if not source_path.exists():
        raise SystemExit(f"Source not found: {source_path}")
    normalized, counts, examples = normalize_text(read_text(source_path))
    write_text(out_path, normalized)
    lines = ["normalize_palochka_final.py report", "", f"Source: {source_path}", f"Output: {out_path}", "", "Counts:"]
    for k, v in counts.items():
        lines.append(f"  {k}: {v}")
    lines += ["", "Examples changed:"]
    for old, new in examples:
        lines.append(f"  {old} -> {new}")
    lines += ["", "Safety note:", "  ASCII-only tokens were not normalized.", "  Roman numerals were not normalized.", "  Tokens starting with I- were not normalized."]
    write_text(report_path, "\n".join(lines) + "\n")
    print(f"Created: {out_path}")
    print(f"Report: {report_path}")
    print(f"Counts: {counts}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
