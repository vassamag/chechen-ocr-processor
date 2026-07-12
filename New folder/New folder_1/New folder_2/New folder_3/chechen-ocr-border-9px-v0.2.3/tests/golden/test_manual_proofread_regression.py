#!/usr/bin/env python3
"""
test_manual_proofread_regression.py

Golden-file regression test: runs the full correction pipeline on the
raw OCR text for pages 11-73 and compares it against the manually
proofread reference, checking that quality hasn't regressed below the
recorded baseline (see baseline.json).

This test is intentionally SEPARATE from the main `pytest tests/` run:
- it needs real book data (raw OCR dump + manually proofread DOCX)
  that is NOT committed to the repo per the project's data policy
  (see tests/golden/data/.gitignore);
- it's slower than the synthetic-dictionary unit tests, since it runs
  the full pipeline on ~60 real pages.

Run explicitly with:

    pytest tests/golden/ -v -m golden

If the data files aren't present locally, the test SKIPS (not fails)
with a message explaining what's missing and where to put it -- so a
fresh clone / CI runner without access to the book data still passes
the rest of the suite cleanly.

To refresh the data (e.g. after re-scanning or manually correcting
more pages), place the two source files at:

    tests/golden/data/raw_ocr_pages_11_73_source.txt
    tests/golden/data/manual_proofread_source.docx

then re-run this test. If metrics improve, update baseline.json
deliberately (it's a checked-in file -- don't let a passing test
silently ratchet the bar down; only move it up, or down with a
documented reason in the commit message).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.golden.golden_diff import run_golden_diff

pytestmark = pytest.mark.golden

DATA_DIR = Path(__file__).parent / "data"
RAW_OCR_PATH = DATA_DIR / "raw_ocr_pages_11_73_source.txt"
MANUAL_DOCX_PATH = DATA_DIR / "manual_proofread_source.docx"
BASELINE_PATH = Path(__file__).parent / "baseline.json"


def _load_baseline() -> dict:
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def _skip_if_data_missing():
    missing = [p for p in (RAW_OCR_PATH, MANUAL_DOCX_PATH) if not p.exists()]
    if missing:
        names = ", ".join(str(p) for p in missing)
        pytest.skip(
            f"Golden-file test data not found locally: {names}. "
            "This is expected on a fresh clone/CI runner -- the book's raw "
            "OCR dump and manually-proofread DOCX are excluded from the repo "
            "per the project's data policy. Place them at the paths above "
            "to run this test."
        )


@pytest.fixture(scope="module")
def golden_report():
    _skip_if_data_missing()
    baseline = _load_baseline()
    page_range = baseline["page_range"]
    return run_golden_diff(
        RAW_OCR_PATH, MANUAL_DOCX_PATH, page_range["first_page"], page_range["last_page"]
    )


def test_overall_word_similarity_meets_baseline(golden_report):
    baseline = _load_baseline()
    expected = baseline["metrics"]["overall_word_similarity_ratio"]
    tolerance = baseline["tolerance"]["overall_word_similarity_ratio"]

    actual = golden_report.overall_similarity_ratio

    assert actual >= expected - tolerance, (
        f"Overall word similarity regressed: {actual:.4f} < "
        f"baseline {expected:.4f} (tolerance {tolerance})"
    )


def test_palochka_recall_meets_baseline(golden_report):
    baseline = _load_baseline()
    expected = baseline["metrics"]["palochka_recall"]
    tolerance = baseline["tolerance"]["palochka_recall"]

    actual = golden_report.palochka_recall

    assert actual >= expected - tolerance, (
        f"Palochka recall regressed: {actual:.4f} < baseline {expected:.4f} (tolerance {tolerance})"
    )


def test_expected_pages_are_still_excluded_for_known_reasons(golden_report):
    """
    Documents (and pins) which pages are excluded and why, so that if the
    underlying raw OCR file is ever updated (e.g. re-scanning page 24 or
    33), this test starts failing here first -- a clear signal to update
    baseline.json's excluded_pages list and re-baseline, rather than the
    exclusion silently persisting forever.
    """
    baseline = _load_baseline()
    expected_excluded = {p for pages in baseline["excluded_pages"].values() for p in pages}

    actual_excluded = {p.page for p in golden_report.pages if p.status != "ok"}

    assert actual_excluded == expected_excluded, (
        f"Set of excluded pages changed: {actual_excluded} vs "
        f"baseline {expected_excluded}. If pages were re-scanned/fixed, "
        f"update tests/golden/baseline.json's excluded_pages and "
        f"re-establish the metrics baseline deliberately."
    )


def test_clean_page_count_matches_baseline(golden_report):
    baseline = _load_baseline()
    expected_count = baseline["clean_page_count"]
    actual_count = len(golden_report.clean_pages)

    assert actual_count == expected_count, (
        f"Number of clean, comparable pages changed: {actual_count} vs "
        f"baseline {expected_count}. This usually means the source data "
        f"files changed -- re-run tests/golden/golden_diff.py manually, "
        f"review the new per-page report, and update baseline.json."
    )
