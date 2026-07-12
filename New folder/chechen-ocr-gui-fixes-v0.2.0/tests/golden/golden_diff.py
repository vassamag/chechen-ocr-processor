#!/usr/bin/env python3
"""
golden_diff.py

Word-level diff harness comparing the corrected pipeline output
against the manually-proofread reference, page by page.

Design choices:
- Word-level (not character-level) diff: readable mismatch reports
  ("хГара" vs "хӀара" is one mismatched word, not N mismatched chars).
- Per-page granularity, not just one aggregate number: this project's
  raw data has real alignment issues (pages missing from the raw OCR
  dump, page numbers attributed to two different photographed pages)
  that must be visible in the report, not averaged away.
- similarity_ratio uses difflib.SequenceMatcher on word lists, which
  handles insertions/deletions (not just substitutions) gracefully --
  important since OCR often drops or duplicates whole words/lines.
"""

from __future__ import annotations

import difflib
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from chechen_ocr import ChechenOcrProcessor, Settings
from tests.golden.extract_manual_reference import extract_pages
from tests.golden.parse_raw_ocr import pages_in_range, parse_raw_ocr

_WORD_RE = re.compile(r"\S+", flags=re.UNICODE)


def tokenize(text: str) -> list[str]:
    return _WORD_RE.findall(text)


@dataclass
class PageDiffReport:
    page: int
    status: str  # "ok" | "missing_in_raw" | "ambiguous_duplicate_in_raw" | "incomplete_raw_scan"
    similarity_ratio: float | None = None
    actual_word_count: int = 0
    expected_word_count: int = 0
    mismatches: list[tuple[str, str]] = field(default_factory=list)
    expected_palochka_count: int = 0
    recovered_palochka_count: int = 0
    unconverted_lookalike_count: int = 0


@dataclass
class GoldenReport:
    pages: list[PageDiffReport]

    @property
    def clean_pages(self) -> list[PageDiffReport]:
        return [p for p in self.pages if p.status == "ok"]

    @property
    def overall_similarity_ratio(self) -> float:
        clean = self.clean_pages
        if not clean:
            return 0.0
        total_expected = sum(p.expected_word_count for p in clean)
        if total_expected == 0:
            return 0.0
        weighted = sum((p.similarity_ratio or 0.0) * p.expected_word_count for p in clean)
        return weighted / total_expected

    @property
    def palochka_recall(self) -> float:
        clean = self.clean_pages
        total_expected = sum(p.expected_palochka_count for p in clean)
        if total_expected == 0:
            return 0.0
        total_recovered = sum(p.recovered_palochka_count for p in clean)
        return total_recovered / total_expected

    @property
    def unconverted_lookalike_count(self) -> int:
        return sum(p.unconverted_lookalike_count for p in self.clean_pages)

    @property
    def total_actual_words(self) -> int:
        return sum(p.actual_word_count for p in self.clean_pages)


_PALOCHKA_LOOKALIKE_RE = re.compile(r"^[^\W\d_]*[Iil1\|!\[\]ЇїЈј][^\W\d_]*$", re.UNICODE)


def diff_words(
    actual_words: list[str], expected_words: list[str]
) -> tuple[float, list[tuple[str, str]]]:
    matcher = difflib.SequenceMatcher(a=actual_words, b=expected_words, autojunk=False)
    ratio = matcher.ratio()

    mismatches: list[tuple[str, str]] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        actual_span = actual_words[i1:i2]
        expected_span = expected_words[j1:j2]
        # Pair them up positionally for a readable report; ragged spans
        # (insert/delete) just show "" on the missing side.
        for k in range(max(len(actual_span), len(expected_span))):
            a = actual_span[k] if k < len(actual_span) else ""
            e = expected_span[k] if k < len(expected_span) else ""
            mismatches.append((a, e))

    return ratio, mismatches


def _palochka_counts(actual_words: list[str], expected_words: list[str]) -> tuple[int, int, int]:
    """
    Returns (expected_palochka_count, recovered_palochka_count, unconverted_lookalike_count).

    expected_palochka_count: how many expected words contain Ӏ.
    recovered_palochka_count: how many of those appear verbatim (whole
        word, via a word-multiset match) somewhere in the actual output.
    unconverted_lookalike_count: how many actual-output words contain an
        un-converted OCR lookalike character (I, i, l, 1, |, !, [, ], Ї,
        ї, Ј, ј) with no Ӏ present -- i.e. cases the pipeline left alone
        (correctly conservative, or a miss -- this count alone can't
        distinguish the two; see suspicious-word reports for that).
    """
    bag: dict[str, int] = {}
    for w in actual_words:
        bag[w] = bag.get(w, 0) + 1

    expected_palochka = 0
    recovered_palochka = 0
    for w in expected_words:
        if "Ӏ" in w:
            expected_palochka += 1
            if bag.get(w, 0) > 0:
                recovered_palochka += 1
                bag[w] -= 1

    unconverted = sum(1 for w in actual_words if "Ӏ" not in w and _PALOCHKA_LOOKALIKE_RE.match(w))

    return expected_palochka, recovered_palochka, unconverted


def run_golden_diff(
    raw_ocr_path: Path,
    manual_docx_path: Path,
    first_page: int,
    last_page: int,
) -> GoldenReport:
    processor = ChechenOcrProcessor(settings=Settings.default())

    raw_blocks_by_page = pages_in_range(
        parse_raw_ocr(raw_ocr_path.read_text(encoding="utf-8", errors="replace")),
        first_page,
        last_page,
    )
    expected_pages = extract_pages(manual_docx_path)

    reports: list[PageDiffReport] = []

    for page in range(first_page, last_page + 1):
        expected_lines = expected_pages.get(page)
        if expected_lines is None:
            # No manually-proofread reference for this page at all --
            # not the same thing as "missing from raw OCR"; skip either way.
            continue

        expected_text = "\n".join(expected_lines)
        expected_words = tokenize(expected_text)

        raw_blocks = raw_blocks_by_page.get(page, [])

        if not raw_blocks:
            reports.append(
                PageDiffReport(
                    page=page,
                    status="missing_in_raw",
                    expected_word_count=len(expected_words),
                )
            )
            continue

        if len(raw_blocks) > 1:
            reports.append(
                PageDiffReport(
                    page=page,
                    status="ambiguous_duplicate_in_raw",
                    expected_word_count=len(expected_words),
                )
            )
            continue

        raw_text = raw_blocks[0].text
        doc = processor.process_text(raw_text)
        actual_words = tokenize(doc.corrected_text)

        # A raw photo that only captured part of the printed page (cropped,
        # cut off mid-sentence) will legitimately produce far fewer words
        # than the manually-proofread reference -- that's a scan-completeness
        # problem, not something the correction pipeline can fix or should
        # be penalized for. Flag it separately instead of quietly dragging
        # the correction-quality number down.
        completeness = len(actual_words) / len(expected_words) if expected_words else 1.0
        if completeness < 0.7:
            reports.append(
                PageDiffReport(
                    page=page,
                    status="incomplete_raw_scan",
                    actual_word_count=len(actual_words),
                    expected_word_count=len(expected_words),
                )
            )
            continue

        ratio, mismatches = diff_words(actual_words, expected_words)

        expected_palochka, recovered_palochka, unconverted = _palochka_counts(
            actual_words, expected_words
        )

        reports.append(
            PageDiffReport(
                page=page,
                status="ok",
                similarity_ratio=ratio,
                actual_word_count=len(actual_words),
                expected_word_count=len(expected_words),
                mismatches=mismatches,
                expected_palochka_count=expected_palochka,
                recovered_palochka_count=recovered_palochka,
                unconverted_lookalike_count=unconverted,
            )
        )

    return GoldenReport(pages=reports)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-ocr", required=True, type=Path)
    parser.add_argument("--manual-docx", required=True, type=Path)
    parser.add_argument("--first-page", type=int, default=11)
    parser.add_argument("--last-page", type=int, default=73)
    parser.add_argument("--show-mismatches", type=int, default=10)
    args = parser.parse_args()

    report = run_golden_diff(args.raw_ocr, args.manual_docx, args.first_page, args.last_page)

    print(f"Pages evaluated (clean, single raw block, complete scan): {len(report.clean_pages)}")
    print(
        f"Overall word-level similarity ratio (correction quality only): {report.overall_similarity_ratio:.4f}"
    )
    print(f"Palochka recall (exact-word recovery of Ӏ-words): {report.palochka_recall:.4f}")
    print(
        f"Unconverted lookalikes remaining: {report.unconverted_lookalike_count} / {report.total_actual_words} words"
    )
    print()

    for p in report.pages:
        if p.status != "ok":
            extra = ""
            if p.status == "incomplete_raw_scan":
                extra = f" ({p.actual_word_count}/{p.expected_word_count} words)"
            print(f"  page {p.page}: SKIPPED ({p.status}){extra}")

    print()
    print("Per-page similarity (worst first):")
    for p in sorted(report.clean_pages, key=lambda p: p.similarity_ratio or 0):
        print(
            f"  page {p.page}: {p.similarity_ratio:.4f}  "
            f"({p.actual_word_count} actual / {p.expected_word_count} expected words)"
        )

    print()
    worst_page = min(report.clean_pages, key=lambda p: p.similarity_ratio or 1.0)
    print(f"Sample mismatches from worst page ({worst_page.page}):")
    for a, e in worst_page.mismatches[: args.show_mismatches]:
        print(f"  actual={a!r:20} expected={e!r}")
