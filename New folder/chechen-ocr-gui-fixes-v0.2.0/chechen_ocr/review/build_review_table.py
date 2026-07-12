"""
build_review_table.py

Builds a human-review table from a ChechenOcrProcessor result: for
each suspicious word, finds its surrounding context in both the raw
(pre-correction) and corrected text, so a reviewer can decide what to
do without needing the original scanned page image.

Ported from src/make_review_table_with_context.py, adapted to work
directly off in-memory ProcessedDocument data (no more re-deriving
"corrected text" from a raw-OCR-plus-corrections-log reconstruction --
we already have the real corrected text and the real correction list
from the pipeline, so that reconstruction step from the original
script is unnecessary here).

Design note: like the original script, context-finding is a sequential
text search by word content (not stored character offsets) -- the
Corrector protocol doesn't currently track exact final positions for
every correction (some, like whole-text regex substitutions, only
report an approximate position; see core.Correction.position). This
keeps the review module decoupled from that -- it can work purely off
ProcessedDocument.raw_text / .corrected_text / .suspicious.
"""

from __future__ import annotations

from ..suspicious import SuspiciousWord
from .schema import ReviewRow, build_page_index, page_for_position

DEFAULT_CONTEXT_CHARS = 160


def _normalize_space(s: str) -> str:
    import re

    return re.sub(r"\s+", " ", s or "").strip()


def _context_around(text: str, word: str, start_pos: int, context_chars: int) -> tuple[str, int]:
    """Finds `word` at/after `start_pos` (falling back to a full-text
    search), and returns a normalized context snippet with the word
    bracketed as [[word]], plus the absolute position found."""
    if not word:
        return "", -1

    pos = text.find(word, max(0, start_pos))
    if pos == -1:
        pos = text.find(word)
    if pos == -1:
        return "", -1

    a = max(0, pos - context_chars)
    b = min(len(text), pos + len(word) + context_chars)

    ctx = text[a:b]
    rel = pos - a
    ctx = ctx[:rel] + "[[" + ctx[rel : rel + len(word)] + "]]" + ctx[rel + len(word) :]

    return _normalize_space(ctx), pos


def _context_at_position(text: str, pos: int, context_chars: int) -> tuple[str, str]:
    """Builds context around a known approximate position, highlighting
    whatever token currently occupies that spot -- used when the
    suspicious raw token was already changed in the corrected text, so
    a direct text search for the original word would fail there."""
    if pos < 0 or pos >= len(text):
        return "", ""

    left = pos
    while left > 0 and not text[left - 1].isspace():
        left -= 1
    right = pos
    while right < len(text) and not text[right].isspace():
        right += 1

    token = text[left:right]
    a = max(0, left - context_chars)
    b = min(len(text), right + context_chars)
    ctx = text[a:left] + "[[" + text[left:right] + "]]" + text[right:b]
    return _normalize_space(ctx), token


def build_review_rows(
    raw_text: str,
    corrected_text: str,
    suspicious_words: list[SuspiciousWord],
    context_chars: int = DEFAULT_CONTEXT_CHARS,
) -> list[ReviewRow]:
    raw_pages = build_page_index(raw_text)
    corrected_pages = build_page_index(corrected_text)

    rows: list[ReviewRow] = []
    raw_search_pos = 0
    corrected_search_pos = 0

    for idx, item in enumerate(suspicious_words, start=1):
        word = item.word

        raw_ctx, raw_pos = _context_around(raw_text, word, raw_search_pos, context_chars)
        corrected_ctx, corrected_pos = _context_around(
            corrected_text, word, corrected_search_pos, context_chars
        )

        corrected_token_at_raw_pos = ""
        if corrected_pos == -1 and raw_pos != -1:
            corrected_ctx, corrected_token_at_raw_pos = _context_at_position(
                corrected_text, raw_pos, context_chars
            )
            corrected_pos = raw_pos

        if corrected_pos != -1:
            corrected_search_pos = corrected_pos + len(word)
        if raw_pos != -1:
            raw_search_pos = raw_pos + len(word)

        page, image_file = "", ""
        if corrected_pos != -1:
            page, image_file = page_for_position(corrected_pages, corrected_pos)
        if not page and raw_pos != -1:
            page, image_file = page_for_position(raw_pages, raw_pos)

        notes = ""
        if corrected_token_at_raw_pos and corrected_token_at_raw_pos != word:
            notes = f"corrected token at raw position: {corrected_token_at_raw_pos}"
        if not corrected_ctx and not raw_ctx:
            notes = (notes + "; " if notes else "") + "context not found"

        rows.append(
            ReviewRow(
                id=idx,
                page=page,
                image_file=image_file,
                word=word,
                reason=item.reason,
                candidates=", ".join(item.candidates),
                corrected_context=corrected_ctx,
                raw_context=raw_ctx,
                decision="pending",
                replacement="",
                notes=notes,
            )
        )

    return rows
