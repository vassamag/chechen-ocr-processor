"""
word_segmentation.py

Splits OCR tokens that merged two or more words together with no
space (a common OCR artifact for justified/dense print), e.g.
"боцушэрнаарахь" -> "боцуш эрна арахь", using chechen_words.txt to
find a valid full segmentation.

This is the classic "word break" problem: does the token decompose,
with no leftover characters, into a sequence of two or more known
dictionary words? Solved here with an iterative suffix-DP (bounded by
MAX_TOKEN_LENGTH so a long non-word token -- garbled OCR noise, a
name, a foreign word -- doesn't cause a combinatorial blowup for no
benefit). No cross-call caching: a merged-word artifact is rare enough
per document that memoizing wouldn't meaningfully help, and would cost
memory for every unique garbled token seen.

Conservative by design, matching this project's other correctors:
only applies a split when the search finds a valid full segmentation,
and only the SHORTEST (fewest-word) one is used, since a token that
happens to decompose into many tiny dictionary words is more likely a
coincidence than a genuine multi-word merge. Ambiguity (multiple
minimal-length segmentations) is treated as "leave it alone" -- same
philosophy as SingleCandidateDictionaryFix's "exactly one candidate"
rule, generalized to segmentations instead of substitutions.

IMPORTANT limitation found via the golden-file harness (see
tests/golden/golden_diff.py): Chechen is highly agglutinative, and a
75k-word general dictionary, however large, cannot cover every
inflected form of every word. A real word simply missing from the
dictionary (an uncommon verb conjugation, say) can coincidentally have
a valid decomposition into two OTHER, unrelated dictionary words -- an
early, more permissive version of this corrector measurably regressed
golden-file quality by wrongly splitting real words this way (e.g.
"дахделча" -> "дах делча", "хотешка" -> "хо тешка", "сатеснера" -> "са
теснера" -- all real, single words). Genuine merged-word artifacts
observed in practice, by contrast, are noticeably longer (12+
characters, 2-3 real words merged, e.g. "боцушэрнаарахь" -> "боцуш
эрна арахь"). MIN_TOKEN_LENGTH and the raised MIN_PIECE_LENGTH below
exist specifically to keep this corrector out of the length range
where coincidental short-word collisions dominated in testing, at the
cost of not catching short merges (two 3-4 letter words) -- an
accepted tradeoff, since the more permissive version was net-harmful
on real data.
"""

from __future__ import annotations

import re

from ..core import Correction, CorrectionResult, PipelineContext

MAX_TOKEN_LENGTH = 32
MIN_TOKEN_LENGTH = 11  # below this, coincidental valid splits of a
# single real (but dictionary-missing) word dominate -- see limitation
# note above. Tuned against the shortest genuine merge observed
# ("боцушэрнаарахь", 14 chars) and the longest false positive observed
# ("сатеснера", 9 chars) in this project's golden-file corpus.
MIN_PIECE_LENGTH = 3  # skip splits that would produce very short pieces

_TOKEN_PATTERN = re.compile(r"[А-Яа-яЁёӀ]+", flags=re.UNICODE)


def _segmentations(word: str, dictionary: frozenset[str]) -> list[tuple[str, ...]]:
    """
    Returns every way `word` (lowercase) can be split into 2+ pieces
    that are all present in `dictionary`, using a suffix-indexed
    dynamic-programming table (solutions[i] = all valid segmentations
    of word[i:]) so each suffix is solved exactly once per call,
    without recursion-depth concerns for tokens up to MAX_TOKEN_LENGTH.
    """
    n = len(word)
    # solutions[i] = list of tuples of pieces that fully segment word[i:]
    solutions: list[list[tuple[str, ...]] | None] = [None] * (n + 1)
    solutions[n] = [()]  # empty suffix segments to "no pieces"

    for i in range(n - 1, -1, -1):
        pieces_here: list[tuple[str, ...]] = []
        for j in range(i + MIN_PIECE_LENGTH, n + 1):
            piece = word[i:j]
            if piece not in dictionary:
                continue
            rest = solutions[j]
            if not rest:
                continue
            for r in rest:
                pieces_here.append((piece, *r))
        solutions[i] = pieces_here or None

    return solutions[0] or []


def find_best_segmentation(word: str, dictionary: frozenset[str]) -> tuple[str, ...] | None:
    """
    Returns the unique shortest (fewest-piece) segmentation of `word`
    into known dictionary words, or None if there isn't a full
    segmentation, or if more than one segmentation ties for shortest
    (ambiguous -> don't guess).
    """
    if len(word) > MAX_TOKEN_LENGTH or len(word) < MIN_TOKEN_LENGTH:
        return None

    all_segmentations = _segmentations(word, dictionary)
    # A "segmentation" of exactly 1 piece means the whole word is
    # already a single dictionary word -- not a merge, nothing to split.
    multi_word = [s for s in all_segmentations if len(s) >= 2]
    if not multi_word:
        return None

    shortest_len = min(len(s) for s in multi_word)
    shortest = [s for s in multi_word if len(s) == shortest_len]

    if len(shortest) != 1:
        return None  # ambiguous -- more than one equally-short split

    return shortest[0]


class WordSegmentationFix:
    """
    Auto-splits a token into space-separated dictionary words only
    when find_best_segmentation finds a unique shortest full
    segmentation. Case is applied per-piece using a simple heuristic:
    the first piece inherits the original token's leading
    capitalization; subsequent pieces are lowercased (merged OCR words
    essentially never have internal capitals in real text).
    """

    name = "word_segmentation"

    def apply(self, text: str, ctx: PipelineContext) -> CorrectionResult:
        dictionary = ctx.dictionaries.chechen_words
        if not dictionary:
            return CorrectionResult(text=text, corrections=[])

        corrections: list[Correction] = []

        def repl(match: re.Match[str]) -> str:
            token = match.group(0)

            if token.lower() in dictionary:
                return token  # already a known word -- nothing to split

            segmentation = find_best_segmentation(token.lower(), dictionary)
            if segmentation is None:
                return token

            pieces = list(segmentation)
            if token[:1].isupper():
                pieces[0] = pieces[0][:1].upper() + pieces[0][1:]

            corrected = " ".join(pieces)
            corrections.append(
                Correction(rule=self.name, before=token, after=corrected, position=match.start())
            )
            return corrected

        new_text = _TOKEN_PATTERN.sub(repl, text)
        return CorrectionResult(text=new_text, corrections=corrections)
