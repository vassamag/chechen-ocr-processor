"""
suspicious.py

Detects words that still look OCR-damaged after the correction
pipeline has run, so they can be surfaced in a review table for a
human to resolve. This intentionally does NOT auto-correct anything;
it only flags + suggests candidates.

Ported from process.py::is_suspicious_word / get_suspicious_candidates
/ detect_suspicious_words, with the module-level SUSPICIOUS_LOG global
replaced by an explicit return value.

DEFAULT_WHITELIST and KNOWN_SUSPICIOUS_CANDIDATES below are the
built-in *fallback* defaults, used by dictionaries.Dictionaries.load()
only when rules/known_suspicious_candidates.yaml isn't present. At
runtime, is_suspicious_word/get_suspicious_candidates always read from
ctx.dictionaries.suspicious_whitelist /
ctx.dictionaries.known_suspicious_candidates -- editing these two
constants directly no longer has any effect once a rules_dir with the
YAML file is in use; edit the YAML instead.
"""

from __future__ import annotations

import re

from .core import PipelineContext, SuspiciousWord
from .correctors.dictionary_candidate import generate_palochka_candidates

_STRIP_CHARS = ".,!?;:()[]{}«»\"'“”„"

SUSPICIOUS_CHARS = ("[", "]", "|", "1")

SUSPICIOUS_PAIRS = [
    "хГ",
    "ХГ",
    "хТ",
    "ХТ",
    "дГ",
    "ДГ",
    "дТ",
    "ДТ",
    "бТ",
    "БТ",
    "КТ",
    "кт",
    "ГТ",
    "гт",
    "йоТ",
    "ЙоТ",
    "хХ",
    "ХХ",
]

_WORD_PATTERN = re.compile(r"[А-Яа-яЁёӀA-Za-z0-9ІіЇїЈј\[\]\|!\-]+", flags=re.UNICODE)

# Words/names known to be correct despite looking "suspicious"
# (e.g. proper nouns with an internal capital letter).
DEFAULT_WHITELIST = frozenset(
    {
        "Маьлха-Аьзни",
        "Маьлха-Аьзнис",
        "Тату-Хепас",
        "Тату-Хепин",
        "JPG-файлов",
    }
)

# Known OCR-damaged forms with a single, already-verified correction.
# Distinct from the dictionary-candidate corrector: these are cases
# where the dictionary lookup alone is not enough to disambiguate
# (typically because the "wrong" reading also parses as a dictionary word,
# or the damage spans more than one lookalike substitution).
KNOWN_SUSPICIOUS_CANDIDATES: dict[str, list[str]] = {
    "Аълбикин": ["Аьлбикин"],
    "Маьлха-Аъзнис": ["Маьлха-Аьзнис"],
    "бТарлаех": ["бӀарлаех"],
    "ДиЙЦинчо": ["Дийцинчо"],
    "ЮьхыШаьржа": ["ЮьхьӀаьржа"],
    "юьхыШаьржа": ["юьхьӀаьржа"],
}


def _clean(word: str) -> str:
    return word.strip(_STRIP_CHARS)


def _is_mixed_case_inside_word(word: str) -> bool:
    if len(word) < 2 or word.isupper():
        return False
    for i, ch in enumerate(word):
        if ch == "Ӏ" or i == 0:
            continue
        if i > 0 and word[i - 1] == "-":
            continue
        if ch.isupper():
            return True
    return False


def _normalize_internal_uppercase_candidate(word: str) -> str | None:
    if not word:
        return None
    chars = list(word)
    changed = False
    for i, ch in enumerate(chars):
        if ch == "Ӏ" or i == 0:
            continue
        if i > 0 and chars[i - 1] == "-":
            continue
        if ch.isupper():
            chars[i] = ch.lower()
            changed = True
    if not changed:
        return None
    candidate = "".join(chars)
    return candidate if candidate != word else None


def is_suspicious_word(
    word: str,
    ctx: PipelineContext,
    whitelist: frozenset[str] | None = None,
) -> tuple[bool, str]:
    if len(word) < 2:
        return False, ""

    clean_word = _clean(word)
    if not clean_word:
        return False, ""

    if clean_word.isdigit():
        return False, ""

    effective_whitelist = (
        whitelist if whitelist is not None else ctx.dictionaries.suspicious_whitelist
    )
    if clean_word in effective_whitelist:
        return False, ""

    if clean_word.lower() in ctx.dictionaries.palochka_words:
        return False, ""

    if clean_word in ctx.dictionaries.known_suspicious_candidates:
        return True, "known OCR pattern"

    for ch in SUSPICIOUS_CHARS:
        if ch in clean_word:
            return True, f"contains suspicious OCR char '{ch}'"

    if "!" in clean_word[:-1]:
        return True, "contains suspicious OCR char '!' inside word"

    if re.search(r"[A-Za-z]", clean_word) and re.search(r"[А-Яа-яЁёӀ]", clean_word):
        return True, "mixed Latin/Cyrillic characters"

    for pair in SUSPICIOUS_PAIRS:
        if pair in clean_word:
            return True, f"suspicious pair '{pair}'"

    if _is_mixed_case_inside_word(clean_word):
        return True, "uppercase letter inside word"

    return False, ""


def get_suspicious_candidates(word: str, ctx: PipelineContext) -> list[str]:
    """
    Suggests candidate corrections for a flagged word, for a human to
    choose from (see review/build_review_table.py, gui/app.py's
    candidate buttons).

    Unlike SingleCandidateDictionaryFix (which only auto-applies a
    candidate that's verified present in palochka_words.txt), this
    surfaces BOTH dictionary-verified candidates and unverified ones
    generated by the same pattern logic (generate_palochka_candidates)
    -- ranked verified-first, then unverified, then the case-only
    fallback. The dictionary gate exists to prevent a wrong auto-
    correction; it should not also hide a plausible, likely-correct
    candidate from a human who is going to judge it visually anyway.
    This matters in practice for Chechen's agglutinative morphology:
    a correctly-generated candidate (e.g. "бТаьхоша" -> "бӀаьхоша") is
    often simply missing from an ~80k-word dictionary as a specific
    inflected form, even though it's obviously correct once you see it.
    """
    clean_word = _clean(word)
    if not clean_word:
        return []

    known = ctx.dictionaries.known_suspicious_candidates
    if clean_word in known:
        return list(known[clean_word])

    dictionary = ctx.dictionaries.palochka_words
    generated = generate_palochka_candidates(clean_word)

    verified = [c for c in generated if c.lower() in dictionary]
    unverified = [c for c in generated if c.lower() not in dictionary]

    candidates = verified + unverified

    lowercase_candidate = _normalize_internal_uppercase_candidate(clean_word)
    if lowercase_candidate:
        candidates.append(lowercase_candidate)

    seen: set[str] = set()
    result = []
    for cand in candidates:
        if cand not in seen:
            result.append(cand)
            seen.add(cand)
    return result


def detect_suspicious_words(
    text: str,
    ctx: PipelineContext,
    whitelist: frozenset[str] | None = None,
) -> list[SuspiciousWord]:
    """Returns deduplicated, order-preserving list of SuspiciousWord."""
    found: list[SuspiciousWord] = []
    seen: set[str] = set()

    for word in _WORD_PATTERN.findall(text):
        is_bad, reason = is_suspicious_word(word, ctx, whitelist)
        if not is_bad:
            continue

        clean_word = _clean(word)
        if clean_word in seen:
            continue
        seen.add(clean_word)

        candidates = get_suspicious_candidates(word, ctx)
        found.append(SuspiciousWord(word=clean_word, reason=reason, candidates=candidates))

    return found
