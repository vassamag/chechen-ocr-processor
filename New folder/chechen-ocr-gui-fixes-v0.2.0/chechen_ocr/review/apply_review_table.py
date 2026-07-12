"""
apply_review_table.py

Safely applies human-reviewed decisions (from a CSV built by
build_review_table.py, or edited directly in the GUI) back onto the
corrected text.

Safety policy (unchanged from the original apply_review_table.py):
- only rows with decision == "replace" and a non-empty replacement
  are applied;
- reject/pending rows are never applied;
- replacement is context-based by default (the row's corrected_context
  snippet must be found in the text; only the bracketed occurrence
  inside that snippet is replaced) -- this avoids accidentally
  replacing an unrelated occurrence of the same word elsewhere in the
  document. The context match tries an exact substring match first,
  then falls back to a whitespace-tolerant regex match (whitespace
  runs in the context match any whitespace in the text) -- needed
  because build_review_table.py normalizes whitespace when building
  the context snippet, while source texts with hard line-wrapped
  paragraphs (a printed line per text line) still have real newlines
  in the actual document;
- a global "replace the one unique occurrence of this word anywhere in
  the text" fallback is opt-in (allow_word_fallback=True), used only
  when the context-based approach fails and exactly one occurrence of
  the bare word exists in the whole text.

Two-pass design (important, found via real-world usage -- see project
discussion): suspicious words on the same page are often close
together, so their saved context windows (~160 chars each way)
routinely overlap -- one row's context can contain another row's
target word. Applying rows one at a time against a text that keeps
being mutated meant an earlier row's edit could silently invalidate a
later row's saved context (the text it was searching for had already
changed), causing it to report "context_not_found" even though
`decision=replace` was set correctly. Fixed by locating every row's
target span against the ORIGINAL, unmodified text first (pass 1), then
applying all accepted replacements in a single pass ordered
right-to-left so earlier character offsets stay valid (pass 2). Two
rows whose located spans would overlap each other are not both
applied; the one considered first (original row order) wins and the
other is marked skipped, rather than risk corrupting the text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

WORD_CHARS = r"A-Za-zА-Яа-яЁёІіЇїӀӏ0-9_"


@dataclass
class ApplyResult:
    row_id: str
    page: str
    word: str
    replacement: str
    status: str
    detail: str


def _token_pattern(token: str) -> re.Pattern[str]:
    escaped = re.escape(token)
    return re.compile(rf"(?<![{WORD_CHARS}]){escaped}(?![{WORD_CHARS}])")


def _locate_word_in_span(text: str, start: int, end: int, word: str) -> tuple[int, int] | None:
    """Finds `word` as a whole token within text[start:end], falling back
    to a plain substring search if no clean word-boundary match exists.
    Returns absolute (start, end) in `text`, or None if not found at all."""
    span = text[start:end]
    match = _token_pattern(word).search(span)
    if match:
        return start + match.start(), start + match.end()
    pos = span.find(word)
    if pos < 0:
        return None
    return start + pos, start + pos + len(word)


def _whitespace_tolerant_pattern(context_exact: str) -> re.Pattern[str]:
    """
    Builds a regex that matches `context_exact` against real text even
    when the real text's whitespace differs from the context's (e.g.
    the context was built from whitespace-normalized text -- see
    review/build_review_table.py's _normalize_space -- while the real
    text still has actual newlines from hard line-wrapped print
    paragraphs). Every run of whitespace in the context becomes `\\s+`;
    everything else is escaped literally.
    """
    parts = re.split(r"(\s+)", context_exact)
    pattern_parts = [r"\s+" if part.strip() == "" and part else re.escape(part) for part in parts]
    return re.compile("".join(pattern_parts))


def _locate_context_span(text: str, context: str) -> tuple[int, int, str] | None:
    """Finds `context` (with [[...]] markers stripped) in `text`, trying
    an exact match first, then a whitespace-tolerant one. Returns
    (start, end, detail) or None."""
    context_exact = context.strip().replace("[[", "").replace("]]", "")
    if not context_exact:
        return None

    pos = text.find(context_exact)
    if pos >= 0:
        return pos, pos + len(context_exact), "applied_context"

    pattern = _whitespace_tolerant_pattern(context_exact)
    match = pattern.search(text)
    if match:
        return match.start(), match.end(), "applied_whitespace_tolerant"

    return None


def _locate_unique_word_span(text: str, word: str) -> tuple[int, int, str] | str:
    """For the word-fallback path: returns (start, end, detail) if `word`
    occurs exactly once in `text`, otherwise a failure-reason string."""
    matches = list(_token_pattern(word).finditer(text))
    if len(matches) == 0:
        return "fallback_word_not_found"
    if len(matches) > 1:
        return f"fallback_ambiguous_{len(matches)}_matches"
    m = matches[0]
    return m.start(), m.end(), "applied_unique_word_fallback"


def _locate_replacement_span(
    text: str, row: dict[str, str], allow_word_fallback: bool
) -> tuple[int, int, str] | str:
    """
    Locates the (start, end) span to replace for one row, against the
    given (stable, not-yet-mutated) `text`. Returns (start, end, detail)
    on success, or a failure-reason string on failure.
    """
    word = (row.get("word") or "").strip()
    context = row.get("corrected_context") or ""

    context_span = _locate_context_span(text, context)
    if context_span is not None:
        c_start, c_end, detail = context_span
        word_span = _locate_word_in_span(text, c_start, c_end, word)
        if word_span is not None:
            return word_span[0], word_span[1], detail
        # Context matched but the word itself wasn't found inside it
        # (shouldn't normally happen -- the context was built to
        # contain the word) -- fall through to context_not_found /
        # word fallback below rather than silently misplacing the edit.

    if allow_word_fallback:
        fallback = _locate_unique_word_span(text, word)
        if not isinstance(fallback, str):
            return fallback

    return "context_not_found"


def apply_review_rows(
    text: str,
    rows: list[dict[str, str]],
    allow_word_fallback: bool = False,
) -> tuple[str, list[ApplyResult]]:
    """
    Applies all rows with decision == "replace" to `text`.

    Returns (new_text, results) -- results has exactly one entry per
    input row, in the same order, for a full audit trail (including
    not-considered / skipped rows).
    """
    original_text = text

    # Pass 1: validate each row and locate its target span against the
    # ORIGINAL, unmodified text (see module docstring for why this must
    # not be done against a progressively-mutated text).
    row_info: list[tuple[str, str, str, str, tuple[int, int] | None, str]] = []
    # (row_id, page, word, replacement, span_or_None, detail)

    for row in rows:
        row_id = row.get("id", "")
        page = row.get("page", "")
        word = (row.get("word") or "").strip()
        replacement = (row.get("replacement") or "").strip()
        decision = (row.get("decision") or "").strip().lower()

        if decision != "replace":
            row_info.append(
                (row_id, page, word, replacement, None, f"decision={decision or 'empty'}")
            )
            continue
        if not word:
            row_info.append((row_id, page, word, replacement, None, "empty_word"))
            continue
        if not replacement:
            row_info.append(
                (row_id, page, word, replacement, None, "replace_with_empty_replacement")
            )
            continue
        if word == replacement:
            row_info.append((row_id, page, word, replacement, None, "word_equals_replacement"))
            continue

        located = _locate_replacement_span(original_text, row, allow_word_fallback)
        if isinstance(located, str):
            row_info.append((row_id, page, word, replacement, None, located))
        else:
            start, end, detail = located
            row_info.append((row_id, page, word, replacement, (start, end), detail))

    # Pass 2: resolve overlaps in original row order (first row to claim
    # a span wins) and apply all accepted spans in one go, right-to-left
    # so earlier character offsets remain valid throughout.
    accepted_spans: list[tuple[int, int]] = []
    results: list[ApplyResult] = []
    to_apply: list[tuple[int, int, str]] = []

    for row_id, page, word, replacement, span, detail in row_info:
        if span is None:
            status = "not_considered" if detail.startswith("decision=") else "skipped"
            results.append(ApplyResult(row_id, page, word, replacement, status, detail))
            continue

        start, end = span
        overlaps = any(not (end <= a_start or start >= a_end) for a_start, a_end in accepted_spans)
        if overlaps:
            results.append(
                ApplyResult(row_id, page, word, replacement, "skipped", "overlaps_another_row")
            )
            continue

        accepted_spans.append(span)
        to_apply.append((start, end, replacement))
        results.append(ApplyResult(row_id, page, word, replacement, "applied", detail))

    to_apply.sort(key=lambda t: t[0], reverse=True)
    for start, end, replacement in to_apply:
        text = text[:start] + replacement + text[end:]

    return text, results
