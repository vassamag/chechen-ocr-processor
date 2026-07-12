"""
general_word_fix.py

Corrects common non-palochka Cyrillic letter-confusion OCR errors,
using chechen_words.txt (a general-purpose Chechen wordlist, not
specific to any one book) as the validation dictionary.

Motivation: golden-file analysis (tests/golden/golden_diff.py) found
that roughly 44% of remaining word-level mismatches after the
palochka-specific correctors run are NOT palochka-related at all --
things like "Аързу" -> "Аьрзу" (ъ/ь confusion), "кҳузахь" -> "кхузахь"
(ҳ/х confusion), "охьзкхачаран" -> "охьакхачаран" (з/а confusion).
This corrector targets exactly that class of error.

Confusion pairs are a small, hand-curated list built from real
observed OCR mistakes (see the pairs below), not a generic "try every
possible letter" edit-distance-1 spellchecker. That's a deliberate
scope limit: with a 75k-word dictionary, blindly substituting any of
~40 Cyrillic letters at every position of every unmatched token would
risk "correcting" a rare-but-real word into a different, more common
one purely by chance. Restricting to letters that are visually
similar (and therefore plausible OCR confusions) keeps the false-
positive rate low, at the cost of not catching confusion pairs that
haven't been observed yet -- extend CONFUSION_PAIRS as new patterns
are found (see tests/golden/golden_diff.py's mismatch reports for
where to look).

Uses the same conservative "exactly one dictionary-valid candidate"
disambiguation strategy as SingleCandidateDictionaryFix.
"""

from __future__ import annotations

import re

from ..core import Correction, CorrectionResult, PipelineContext
from .dictionary_candidate import preserve_case, split_token

# (confused_char, correct_char) -- visually similar Cyrillic letters
# observed to be swapped by OCR in real text. Order matters: only the
# confused_char -> correct_char direction is tried (e.g. we've only
# observed OCR misreading а as з, not the other way around, in this
# corpus -- if that reverses in a different scan batch, add the
# opposite-direction pair too).
CONFUSION_PAIRS: tuple[tuple[str, str], ...] = (
    ("ъ", "ь"),
    ("з", "а"),
    ("ҳ", "х"),
    ("ав", "аь"),
    ("аы", "аь"),
)

_TOKEN_PATTERN = re.compile(r"[А-Яа-яЁёӀҲҳA-Za-z0-9\-]+", flags=re.UNICODE)


def generate_confusion_candidates(word: str) -> set[str]:
    """
    Generates candidates by substituting each occurrence of a
    confused_char with its correct_char, one confusion pair at a time
    (not all combinations at once -- most real errors involve exactly
    one confused letter per word).
    """
    candidates: set[str] = set()
    lower_word = word.lower()

    for confused, correct in CONFUSION_PAIRS:
        if confused in lower_word:
            candidates.add(lower_word.replace(confused, correct))

    return candidates


class GeneralWordFix:
    """
    Auto-corrects a token only when generate_confusion_candidates()
    yields exactly one candidate present in the general Chechen
    wordlist (ctx.dictionaries.chechen_words). Ambiguous or unmatched
    tokens are left untouched, same philosophy as the palochka
    dictionary corrector.
    """

    name = "general_word_fix"

    def apply(self, text: str, ctx: PipelineContext) -> CorrectionResult:
        dictionary = ctx.dictionaries.chechen_words
        if not dictionary:
            return CorrectionResult(text=text, corrections=[])

        corrections: list[Correction] = []

        def repl(match: re.Match[str]) -> str:
            token = match.group(0)
            prefix, core, suffix = split_token(token)

            if not core or core.isdigit():
                return token
            if core.lower() in dictionary:
                return token

            candidates = generate_confusion_candidates(core)
            valid = sorted({c for c in candidates if c in dictionary}, key=len)

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
