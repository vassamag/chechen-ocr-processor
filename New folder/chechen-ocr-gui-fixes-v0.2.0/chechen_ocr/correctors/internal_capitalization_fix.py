"""
internal_capitalization_fix.py

Lowercases a capital Cyrillic letter that appears anywhere in a word
EXCEPT the first character -- genuine Chechen text (like most
Cyrillic-script orthographies) essentially only capitalizes the first
letter of a word (for sentence-initial position or a proper noun).
A capital letter turning up in the middle or at the end of a word is
therefore a case error, not a meaningful distinction, regardless of
which specific letter it is.

Raised via project discussion: started as a narrower hypothesis (only
capital Ш/П/И mid-word are errors, and specifically represent a
palochka substitution). That letter-identity claim didn't hold up
under the same dictionary-verification check that worked well for
6.9.2-6.9.4 (I/i/1/l): confirmation rates were low (0-15%) and, more
tellingly, showed no concentration around any particular preceding
letter (a ГӀ-specific version of the hypothesis was tested and also
rejected). But a simpler, letter-independent hypothesis -- "the
capital is just a case error, fix the CASE, not the letter identity" --
is safer than a letter-substitution claim: it doesn't assert what the
letter should have been instead, only that it shouldn't be capitalized
where it is. Generalized to every letter rather than kept narrow,
since the underlying justification (Cyrillic capitals only belong at
the start of a word) doesn't depend on which letter it happens to be.

This reuses the exact exemption logic already used by
suspicious.py::_normalize_internal_uppercase_candidate (which only
ever offered this as a SUGGESTION for human review, never applied it):
- A fully-uppercase word (a title, a stylized heading) is left alone.
- The palochka (Ӏ) has no case distinction and is never touched.
- A capital immediately after a hyphen is left alone -- that's the
  start of the second part of a hyphenated compound proper noun (e.g.
  "Муса-Паша"), which is legitimate capitalization, not an error.

NOT INCLUDED FOR TESSERACT OUTPUT (see processor.build_pipeline()).
Golden-file testing found a real regression when it ran unconditionally
for every engine: on Tesseract output, an unexpectedly-capitalized
letter is very often the FIRST symptom of a still-unresolved palochka
lookalike -- e.g. "тГаьххьара" should become "тӀаьххьара" via the
тг->тӀ pattern PatternBasedPalochka already knows about, but that
corrector's pattern only matches lowercase "г", not the capital "Г"
this OCR artifact produced. Applying this fix BEFORE that gets
resolved silently "fixes" the case into a confidently wrong word
("тгаьххьара") and -- worse -- removes it from the suspicious-word
queue entirely, since it's no longer mixed-case. Previously such a
word stayed visibly broken and got a human's attention; this
corrector, applied unconditionally, made it look done without being
right. Dropped overall similarity 92.41% -> 92.26% and palochka recall
77.33% -> 76.45% on the golden (Tesseract) corpus.
Vision-generated text doesn't have this collision nearly as often --
measured at 0.2% (4 of 1,851 cases) on a full 590-page real book,
since Vision output doesn't suffer from PatternBasedPalochka's
lowercase-only matching gap the same way scanned-glyph OCR does. So
this corrector is engine-gated the OPPOSITE way from the Tesseract-
specific correctors: enabled for every engine EXCEPT Tesseract.
"""

from __future__ import annotations

import re

from ..core import Correction, CorrectionResult, PipelineContext

_TOKEN_PATTERN = re.compile(r"[А-Яа-яЁёӀӏ]+")


def _fix_token(token: str) -> str | None:
    """Returns the case-fixed token, or None if nothing needed fixing."""
    if len(token) < 2 or token.isupper():
        return None

    chars = list(token)
    changed = False
    for i, ch in enumerate(chars):
        if i == 0 or ch == "Ӏ":
            continue
        if chars[i - 1] == "-":
            continue
        if ch.isupper():
            chars[i] = ch.lower()
            changed = True

    return "".join(chars) if changed else None


class InternalCapitalizationFix:
    """
    Lowercases any capital Cyrillic letter found after the first
    character of a word, except one immediately following a hyphen
    (start of the second part of a hyphenated compound name) or the
    palochka (Ӏ, which has no case). Fully-uppercase words (titles,
    headings) are left untouched entirely.
    """

    name = "internal_capitalization_fix"

    def apply(self, text: str, ctx: PipelineContext) -> CorrectionResult:
        corrections: list[Correction] = []

        def repl(match: re.Match[str]) -> str:
            token = match.group(0)
            fixed = _fix_token(token)
            if fixed is None:
                return token
            corrections.append(
                Correction(rule=self.name, before=token, after=fixed, position=match.start())
            )
            return fixed

        new_text = _TOKEN_PATTERN.sub(repl, text)
        return CorrectionResult(text=new_text, corrections=corrections)
