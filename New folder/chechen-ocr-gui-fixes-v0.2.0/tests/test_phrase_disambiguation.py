from chechen_ocr.config import Settings
from chechen_ocr.core import PipelineContext
from chechen_ocr.correctors.phrase_disambiguation import PhraseBigramDisambiguator
from chechen_ocr.dictionaries import Dictionaries

# "к1а]н" is a genuinely ambiguous OCR token: it generates exactly two
# dictionary-candidate corrections, "кӀа]н" (via '1'->Ӏ) and "к1аӀн"
# (via ']'->Ӏ) -- see tests/test_dictionary_candidate.py for the same
# fixture word used to test SingleCandidateDictionaryFix's refusal to
# guess between them. Both must be present in palochka_words for both
# to be considered "valid" candidates here.
AMBIGUOUS_WORD = "к1а]н"
CANDIDATE_A = "кӀа]н"
CANDIDATE_B = "к1аӀн"


def _ctx(
    palochka_words: frozenset[str], phrase_bigrams: frozenset[tuple[str, str]]
) -> PipelineContext:
    return PipelineContext(
        settings=Settings.default(),
        dictionaries=Dictionaries(palochka_words=palochka_words, phrase_bigrams=phrase_bigrams),
    )


def test_disambiguates_using_right_neighbor_bigram():
    corrector = PhraseBigramDisambiguator()
    ctx = _ctx(
        palochka_words=frozenset({CANDIDATE_A.lower(), CANDIDATE_B.lower()}),
        phrase_bigrams=frozenset({(CANDIDATE_A.lower(), "лаг")}),
    )

    result = corrector.apply(f"дукха {AMBIGUOUS_WORD} лаг", ctx)

    assert CANDIDATE_A in result.text
    assert result.corrections[0].rule == "phrase_bigram_disambiguation"


def test_disambiguates_using_left_neighbor_bigram():
    corrector = PhraseBigramDisambiguator()
    ctx = _ctx(
        palochka_words=frozenset({CANDIDATE_A.lower(), CANDIDATE_B.lower()}),
        phrase_bigrams=frozenset({("дукха", CANDIDATE_B.lower())}),
    )

    result = corrector.apply(f"дукха {AMBIGUOUS_WORD} зуда", ctx)

    assert CANDIDATE_B in result.text


def test_no_disambiguation_when_neither_candidate_has_bigram_support():
    corrector = PhraseBigramDisambiguator()
    ctx = _ctx(
        palochka_words=frozenset({CANDIDATE_A.lower(), CANDIDATE_B.lower()}),
        phrase_bigrams=frozenset({("unrelated", "bigram")}),
    )

    result = corrector.apply(f"дукха {AMBIGUOUS_WORD} зуда", ctx)

    # Neither candidate is supported -- stay conservative, don't guess.
    assert AMBIGUOUS_WORD in result.text
    assert result.corrections == []


def test_no_op_when_only_one_candidate_exists():
    # Only one of the two candidates is in the dictionary -- not
    # ambiguous at all. SingleCandidateDictionaryFix would already have
    # handled this earlier in the pipeline; this corrector should not
    # duplicate that work.
    corrector = PhraseBigramDisambiguator()
    ctx = _ctx(
        palochka_words=frozenset({CANDIDATE_A.lower()}),  # only one candidate possible
        phrase_bigrams=frozenset({("дукха", CANDIDATE_A.lower())}),
    )

    result = corrector.apply(f"дукха {AMBIGUOUS_WORD}", ctx)

    assert result.corrections == []


def test_empty_bigrams_is_a_no_op():
    corrector = PhraseBigramDisambiguator()
    ctx = _ctx(
        palochka_words=frozenset({CANDIDATE_A.lower(), CANDIDATE_B.lower()}),
        phrase_bigrams=frozenset(),
    )

    result = corrector.apply(f"дукха {AMBIGUOUS_WORD} зуда", ctx)

    assert result.corrections == []


def test_ambiguous_when_both_candidates_have_bigram_support():
    corrector = PhraseBigramDisambiguator()
    ctx = _ctx(
        palochka_words=frozenset({CANDIDATE_A.lower(), CANDIDATE_B.lower()}),
        phrase_bigrams=frozenset({("дукха", CANDIDATE_A.lower()), ("дукха", CANDIDATE_B.lower())}),
    )

    result = corrector.apply(f"дукха {AMBIGUOUS_WORD} зуда", ctx)

    # Both candidates are supported -- still ambiguous, don't guess.
    assert result.corrections == []
