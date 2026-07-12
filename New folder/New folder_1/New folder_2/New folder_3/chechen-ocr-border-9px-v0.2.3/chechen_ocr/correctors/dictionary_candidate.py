"""
Dictionary-based disambiguation: for each word-like token, generate
every plausible "OCR lookalike -> Ӏ" substitution, then auto-correct
only if EXACTLY ONE of the generated candidates exists in the
palochka word dictionary.

This is the core precision-over-recall heuristic of the whole
project: ambiguous words (more than one dictionary-valid candidate,
or none at all) are left untouched and instead surface later via the
suspicious-word detector, for human review.

Ported from process.py::generate_palochka_candidates /
fix_words_using_palochka_dictionary / split_token / preserve_case.

Bug fix vs. the original: in process.py, `pair_replacements` was
accidentally defined *inside* the `for bad, good in lookalikes.items()`
loop due to an indentation slip, so the dict (and the loop that
consumes it) was rebuilt on every iteration of the outer loop. It was
harmless in practice (results are deduplicated via a set), but wasteful
and confusing. Here `PAIR_REPLACEMENTS` is a module-level constant,
built once.
"""

from __future__ import annotations

import re

from ..core import Correction, CorrectionResult, PipelineContext

SINGLE_CHAR_LOOKALIKES: dict[str, str] = {
    "I": "Ӏ",
    "i": "Ӏ",
    "l": "Ӏ",
    "1": "Ӏ",
    "|": "Ӏ",
    "!": "Ӏ",
    "[": "Ӏ",
    "]": "Ӏ",
    "І": "Ӏ",
    "і": "Ӏ",
    "Ї": "Ӏ",
    "ї": "Ӏ",
    "Ј": "Ӏ",
    "ј": "Ӏ",
}

# Two-character OCR-damage patterns where the second character is
# likely a mangled palochka glyph attached to the first (base) letter.
PAIR_REPLACEMENTS: dict[str, str] = {
    "кт": "кӀ",
    "кТ": "кӀ",
    "КТ": "КӀ",
    "кг": "кӀ",
    "кГ": "кӀ",
    "КГ": "КӀ",
    "хг": "хӀ",
    "хГ": "хӀ",
    "ХГ": "ХӀ",
    "хт": "хӀ",
    "хТ": "хӀ",
    "ХТ": "ХӀ",
    "дг": "дӀ",
    "дГ": "дӀ",
    "ДГ": "ДӀ",
    "дт": "дӀ",
    "дТ": "дӀ",
    "ДТ": "ДӀ",
    "бт": "бӀ",
    "бТ": "бӀ",
    "БТ": "БӀ",
    "бг": "бӀ",
    "бГ": "бӀ",
    "БГ": "БӀ",
    "гт": "гӀ",
    "гТ": "гӀ",
    "ГТ": "ГӀ",
    "тг": "тӀ",
    "тГ": "тӀ",
    "ТГ": "ТӀ",
    "пг": "пӀ",
    "пГ": "пӀ",
    "ПГ": "ПӀ",
    "цт": "цӀ",
    "цТ": "цӀ",
    "ЦТ": "ЦӀ",
    "чт": "чӀ",
    "чТ": "чӀ",
    "ЧТ": "ЧӀ",
    "йот": "йоӀ",
    "йоТ": "йоӀ",
    "ЙоТ": "ЙоӀ",
}

_TOKEN_PATTERN = re.compile(r"[А-Яа-яЁёӀA-Za-z0-9ІіЇїЈј\[\]\|!]+", flags=re.UNICODE)


def generate_palochka_candidates(word: str) -> set[str]:
    """Generates possible corrections by replacing OCR lookalikes with Ӏ."""
    candidates: set[str] = set()

    if not word:
        return candidates

    lower_word = word.lower()

    for bad, good in SINGLE_CHAR_LOOKALIKES.items():
        if bad in word:
            candidates.add(word.replace(bad, good))
            candidates.add(lower_word.replace(bad.lower(), good))

    for before, after in PAIR_REPLACEMENTS.items():
        if before in word:
            candidates.add(word.replace(before, after))

    return candidates


def split_token(token: str) -> tuple[str, str, str]:
    """Splits token into prefix punctuation, core word, suffix punctuation."""
    match = re.match(r"^([^А-Яа-яЁёӀA-Za-z0-9]*)(.*?)([^А-Яа-яЁёӀA-Za-z0-9]*)$", token)
    if not match:
        return "", token, ""
    return match.group(1), match.group(2), match.group(3)


def preserve_case(original: str, candidate: str) -> str:
    """Preserves simple capitalization style (all-caps / title-case)."""
    if not original:
        return candidate
    if original.isupper():
        return candidate.upper()
    if original[0].isupper():
        return candidate[:1].upper() + candidate[1:]
    return candidate


class SingleCandidateDictionaryFix:
    """
    Auto-corrects a token only when generate_palochka_candidates()
    yields exactly one candidate that exists in the palochka
    dictionary (case-insensitively). Ambiguous or unmatched tokens are
    left untouched.
    """

    name = "dictionary_single_candidate"

    def apply(self, text: str, ctx: PipelineContext) -> CorrectionResult:
        dictionary = ctx.dictionaries.palochka_words
        if not dictionary:
            return CorrectionResult(text=text, corrections=[])

        corrections: list[Correction] = []

        def repl(match: re.Match[str]) -> str:
            token = match.group(0)
            prefix, core, suffix = split_token(token)

            if not core:
                return token
            if core.isdigit():
                return token
            if core.lower() in dictionary:
                return token

            candidates = generate_palochka_candidates(core)
            valid = sorted({c for c in candidates if c.lower() in dictionary}, key=len)

            if len(valid) == 1:
                corrected_core = preserve_case(core, valid[0])
                corrections.append(
                    Correction(
                        rule=self.name,
                        before=core,
                        after=corrected_core,
                        position=match.start(),
                    )
                )
                return prefix + corrected_core + suffix

            return token

        new_text = _TOKEN_PATTERN.sub(repl, text)
        return CorrectionResult(text=new_text, corrections=corrections)
