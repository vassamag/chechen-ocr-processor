"""
latin_cyrillic_homoglyphs.py

Fixes two related artifacts found in Vision-API-generated text (as
opposed to text OCR'd from a scanned image, which is where every
other corrector in this package focuses):

1. Individual Latin letters that are visually IDENTICAL to a Cyrillic
   letter get generated in the middle of an otherwise-Cyrillic word --
   e.g. "цхаьццa" ends with a Latin "a" (U+0061), not the Cyrillic "а"
   (U+0430) used everywhere else in the same word.
2. Latin "I"/"i" and the digit "1" used in place of the palochka (Ӏ,
   U+04C0) -- the same lookalike confusion every other corrector in
   this package already handles, but here occurring as a generation
   artifact rather than a scanned-glyph misreading.

This is a known behavior of LLM text generation for Cyrillic scripts,
not a reading/recognition error the way a scanned-image OCR mistake
is -- there's no ambiguity about what the writer meant, just which of
several identical- or near-identical-looking Unicode code points the
model happened to emit.

Found via project discussion: running the full "Эха буьйсанаш" book
through the OpenAI Vision API directly (chechen_ocr/ocr/vision_api_engine.py)
produced a suspicious-word rate of ~11.5%, dramatically higher than the
~1-2% seen from the same model used through the ChatGPT chat product.
68% of flagged words in a 50-page sample turned out to be exactly this
homoglyph-mixing artifact, not genuine transcription problems.

Unlike every other corrector in this package, neither fix here needs
dictionary verification or a single-candidate check before applying:
the "correction" isn't a guess among several plausible readings, it's
resolving which of several identical-looking code points was intended.

- Letters (a/e/o/p/c/x/y/B/H/K/M/T, I/i -> Ӏ): a word is only touched
  if it contains BOTH at least one unambiguous Cyrillic letter AND at
  least one Latin letter that has an exact look-alike -- so real
  Latin-only tokens (acronyms, Roman numerals, foreign proper nouns)
  are left alone.
- Digit "1" -> Ӏ: only when the "1" is glued directly to Cyrillic
  letters (start, middle, or end of an otherwise-Cyrillic token) AND
  is not itself part of a longer run of digits -- so a standalone
  number (a year, a page number, "10", "2014") is never touched, even
  if it ends up adjacent to Cyrillic text for some other reason.
  Verified against real book data first: of ~3,600 word-adjacent "1"
  occurrences in "Эха буьйсанаш", ZERO were already valid dictionary
  words as literal digits, while 23-36% became verified dictionary
  words after this substitution (the rest are very likely also
  correct, for word forms simply missing from the dictionary -- the
  same structural gap documented since 6.4.0).
"""

from __future__ import annotations

import re

from ..core import Correction, CorrectionResult, PipelineContext

# Latin -> Cyrillic, restricted to letter PAIRS that are visually
# identical (not just similar) in essentially any font, plus I/i/l,
# which map to the palochka (Ӏ) rather than a plain Cyrillic letter --
# see the inline notes on each below. The digit "1" is handled
# separately (_ISOLATED_DIGIT_ONE), since -- unlike a single letter --
# it needs a "not part of a longer digit run" guard to avoid
# corrupting a genuine multi-digit number.
LATIN_TO_CYRILLIC: dict[str, str] = {
    "a": "а",
    "A": "А",
    "e": "е",
    "E": "Е",
    "o": "о",
    "O": "О",
    "p": "р",
    "P": "Р",
    "c": "с",
    "C": "С",
    "x": "х",
    "X": "Х",
    "y": "у",
    "Y": "У",
    "B": "В",
    "H": "Н",
    "K": "К",
    "M": "М",
    "T": "Т",
    "I": "Ӏ",
    "i": "Ӏ",
    # Lowercase Latin "l" -> palochka too. Found via the same
    # diagnostic process as I/i/1 above: after adding those, "l" turned
    # out to be the single largest remaining cause of "mixed Latin/
    # Cyrillic" flags on real book data (2,213 of ~3,133 occurrences).
    # Verified the same way: 0% of word-adjacent "l" tokens were
    # already valid dictionary words, 21-39% became verified after this
    # substitution. Uppercase "L" is deliberately NOT included --
    # capital Latin L is comparatively rare and less clearly always-
    # wrong than its lowercase form was in the data actually checked.
    "l": "Ӏ",
    # t/k/n/u -> т/к/н/у. Found via project discussion on a second,
    # different book's Vision output ("pages_new_full", 209 pages):
    # this source showed a much wider spread of unmapped Latin letters
    # causing "mixed Latin/Cyrillic" flags than "Эха буьйсанаш" had.
    # Verified each candidate the same way as I/i/1/l: 0% of
    # word-adjacent tokens were already valid dictionary words for any
    # of them. These four had the strongest confirmation after
    # substitution (t: 19.6% of 51, k: 22.7% of 22, n: 16.0% of 25,
    # u: 15.8% of 19) -- comparable to the 15-39% range that supported
    # 1/l. Weaker candidates from the same check (h->х 4.2%, m->м
    # 5.9%, d->д 6.7%, r->г 3.0%) were NOT added -- too little
    # confirmation to be confident, and r/г in particular aren't even
    # clearly visual look-alikes to begin with.
    "t": "т",
    "k": "к",
    "n": "н",
    "u": "у",
}

_UNAMBIGUOUS_CYRILLIC = re.compile(
    r"[бвгджзийклмнпрстуфхцчшщъьэюяёБВГДЖЗИЙКЛМНПРСТУФХЦЧШЩЪЬЭЮЯЁӀӏ]"
)
_MAPPABLE_LATIN = re.compile("[" + re.escape("".join(LATIN_TO_CYRILLIC)) + "]")
# Token pattern includes digits so a "1" glued to letters (start,
# middle, or end) is captured as part of the SAME token as its
# neighbors -- required for the isolated-digit check below to see the
# whole context, and for a pure-digit token (a year, a page number) to
# still be recognized as one token that _UNAMBIGUOUS_CYRILLIC correctly
# rejects (no letters in it at all).
_TOKEN_PATTERN = re.compile(r"[A-Za-zА-Яа-яЁёӀӏ0-9]+")
# A "1" not immediately preceded or followed by another digit -- i.e.
# not part of a multi-digit number like "2014" or "10".
_ISOLATED_DIGIT_ONE = re.compile(r"(?<!\d)1(?!\d)")


class LatinCyrillicHomoglyphFix:
    """
    Replaces Latin homoglyph characters (and, separately, an isolated
    digit "1") with their Cyrillic/palochka counterparts, but only
    within a token that also contains at least one letter that is
    unambiguously Cyrillic (i.e. has no Latin look-alike at all) -- a
    pure Latin token (an acronym, a Roman numeral, an English word) or
    a pure number (a year, a page count) is left completely untouched.
    """

    name = "latin_cyrillic_homoglyph_fix"

    def apply(self, text: str, ctx: PipelineContext) -> CorrectionResult:
        corrections: list[Correction] = []

        def repl(match: re.Match[str]) -> str:
            token = match.group(0)

            if not _UNAMBIGUOUS_CYRILLIC.search(token):
                return token  # pure-Latin / pure-numeric token -- leave alone

            has_mappable_letter = bool(_MAPPABLE_LATIN.search(token))
            has_isolated_one = bool(_ISOLATED_DIGIT_ONE.search(token))
            if not has_mappable_letter and not has_isolated_one:
                return token  # already fully Cyrillic -- nothing to fix

            fixed = "".join(LATIN_TO_CYRILLIC.get(ch, ch) for ch in token)
            fixed = _ISOLATED_DIGIT_ONE.sub("Ӏ", fixed)

            if fixed != token:
                corrections.append(
                    Correction(rule=self.name, before=token, after=fixed, position=match.start())
                )
            return fixed

        new_text = _TOKEN_PATTERN.sub(repl, text)
        return CorrectionResult(text=new_text, corrections=corrections)
