"""
phrase_disambiguation.py

Uses a word-bigram index built from chechen_phrases.txt (see
dictionaries.Dictionaries.phrase_bigrams) to break ties for words
where SingleCandidateDictionaryFix found MORE than one dictionary-
valid palochka candidate and therefore, correctly, left the word
untouched.

The idea: even if two candidate corrections are both individually
valid Chechen words, usually only one of them makes sense next to the
word's actual left/right neighbor in the sentence. Checking whether
(neighbor, candidate) or (candidate, neighbor) occurs as a bigram
anywhere in the reference phrase corpus is a cheap, coarse stand-in
for "does this reading make grammatical/collocational sense here" --
far short of real language modeling, but enough to resolve some of the
cases the pure dictionary-membership check can't.

Scope note: chechen_phrases.txt is a general Chechen reference corpus
(not specific to whatever book is being corrected), so bigram coverage
reflects general collocation patterns, not "this exact phrase already
appeared in this book." Coverage is necessarily partial -- most
ambiguous words will still find no bigram support either way and stay
untouched, which is the conservative, intended behavior.

This corrector must run in the same pass as (or after)
SingleCandidateDictionaryFix, re-deriving the ambiguous-candidate set
independently rather than consuming SingleCandidateDictionaryFix's
output, since Correction objects don't currently carry "this token was
considered but left ambiguous" metadata.
"""

from __future__ import annotations

import re

from ..core import Correction, CorrectionResult, PipelineContext
from .dictionary_candidate import generate_palochka_candidates, preserve_case, split_token

_TOKEN_PATTERN = re.compile(r"[А-Яа-яЁёӀA-Za-z0-9ІіЇїЈј\[\]\|!]+", flags=re.UNICODE)
_STRIP_CHARS = ".,!?;:()[]{}«»\"'“”„-—"


def _neighbor_word(text: str, pos: int, direction: int) -> str:
    """Finds the plain-word neighbor immediately before (direction=-1)
    or after (direction=+1) position `pos` in `text`, skipping
    whitespace, and returns it lowercased/stripped of punctuation."""
    n = len(text)

    if direction < 0:
        end = pos
        while end > 0 and text[end - 1].isspace():
            end -= 1
        start = end
        while start > 0 and not text[start - 1].isspace():
            start -= 1
        word = text[start:end]
    else:
        start = pos
        while start < n and text[start].isspace():
            start += 1
        end = start
        while end < n and not text[end].isspace():
            end += 1
        word = text[start:end]

    return word.strip(_STRIP_CHARS).lower()


class PhraseBigramDisambiguator:
    name = "phrase_bigram_disambiguation"

    def apply(self, text: str, ctx: PipelineContext) -> CorrectionResult:
        palochka_dictionary = ctx.dictionaries.palochka_words
        bigrams = ctx.dictionaries.phrase_bigrams
        if not palochka_dictionary or not bigrams:
            return CorrectionResult(text=text, corrections=[])

        corrections: list[Correction] = []

        def repl(match: re.Match[str]) -> str:
            token = match.group(0)
            prefix, core, suffix = split_token(token)

            if not core or core.isdigit():
                return token
            if core.lower() in palochka_dictionary:
                return token

            candidates = generate_palochka_candidates(core)
            valid = sorted({c for c in candidates if c.lower() in palochka_dictionary})

            if len(valid) < 2:
                # 0 candidates: nothing to disambiguate here.
                # 1 candidate: SingleCandidateDictionaryFix already
                # would have applied it earlier in the pipeline.
                return token

            left = _neighbor_word(text, match.start(), direction=-1)
            right = _neighbor_word(text, match.end(), direction=+1)

            supported = [
                c for c in valid if (left, c.lower()) in bigrams or (c.lower(), right) in bigrams
            ]

            if len(supported) == 1:
                corrected_core = preserve_case(core, supported[0])
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
