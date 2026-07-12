from chechen_ocr.config import Settings
from chechen_ocr.core import PipelineContext
from chechen_ocr.correctors.word_segmentation import (
    WordSegmentationFix,
    find_best_segmentation,
)
from chechen_ocr.dictionaries import Dictionaries


def _ctx(chechen_words: frozenset[str]) -> PipelineContext:
    return PipelineContext(
        settings=Settings.default(),
        dictionaries=Dictionaries(chechen_words=chechen_words),
    )


def test_splits_two_merged_words():
    corrector = WordSegmentationFix()
    ctx = _ctx(frozenset({"боцуш", "эрна", "арахь", "висарна", "а"}))

    result = corrector.apply("боцушэрнаарахь дела", ctx)

    assert result.text == "боцуш эрна арахь дела"
    assert result.corrections[0].rule == "word_segmentation"


def test_splits_three_merged_words():
    corrector = WordSegmentationFix()
    ctx = _ctx(frozenset({"боцуш", "эрна", "арахь"}))

    result = corrector.apply("боцушэрнаарахь", ctx)

    assert result.text == "боцуш эрна арахь"


def test_does_not_touch_already_valid_word():
    corrector = WordSegmentationFix()
    ctx = _ctx(frozenset({"дела"}))

    result = corrector.apply("дела", ctx)

    assert result.text == "дела"
    assert result.corrections == []


def test_no_split_when_no_valid_segmentation_exists():
    corrector = WordSegmentationFix()
    ctx = _ctx(frozenset({"дела"}))

    result = corrector.apply("гарбидж", ctx)

    assert result.text == "гарбидж"
    assert result.corrections == []


def test_preserves_leading_capitalization_on_first_piece():
    corrector = WordSegmentationFix()
    ctx = _ctx(frozenset({"боцуш", "эрнаарахь"}))

    result = corrector.apply("Боцушэрнаарахь", ctx)

    assert result.text == "Боцуш эрнаарахь"


def test_ambiguous_segmentation_is_left_alone():
    # "тотота" has two equally-short (2-piece) valid segmentations in
    # this dictionary: ("то","тота") and ("тото","та"). A genuine tie
    # -- same philosophy as SingleCandidateDictionaryFix's "exactly one
    # candidate" rule -- means don't guess, leave the token untouched.
    corrector = WordSegmentationFix()
    ctx = _ctx(frozenset({"то", "тота", "тото", "та"}))

    result = corrector.apply("тотота", ctx)

    assert result.text == "тотота"
    assert result.corrections == []


def test_find_best_segmentation_returns_none_for_ambiguous_case():
    dictionary = frozenset({"то", "тота", "тото", "та"})
    assert find_best_segmentation("тотота", dictionary) is None


def test_find_best_segmentation_finds_unique_split():
    dictionary = frozenset({"боцуш", "эрнаарахь"})
    assert find_best_segmentation("боцушэрнаарахь", dictionary) == ("боцуш", "эрнаарахь")


def test_single_letter_pieces_are_not_produced():
    # MIN_PIECE_LENGTH=3 should prevent splitting into single-letter or
    # 2-letter pieces even if those short strings happen to be "valid"
    # entries -- token below MIN_TOKEN_LENGTH is a separate, faster
    # rejection path (see test below), so use a long-enough token here
    # to isolate the piece-length check specifically.
    ctx = _ctx(frozenset({"а", "боцушэрнаарахь"}))
    corrector = WordSegmentationFix()

    result = corrector.apply("абоцушэрнаарахь", ctx)

    # "а" + "боцушэрнаарахь" would be a valid split by dictionary
    # membership alone, but the "а" piece is below MIN_PIECE_LENGTH.
    assert result.text == "абоцушэрнаарахь"
    assert result.corrections == []


def test_token_below_min_length_is_never_attempted():
    # "боцушдела" (9 chars) is below MIN_TOKEN_LENGTH=11 -- even though
    # it has a perfectly valid 2-word decomposition, this corrector
    # intentionally won't attempt it (see module docstring: this length
    # range is where real-but-dictionary-missing single words
    # coincidentally collide with valid short decompositions).
    dictionary = frozenset({"боцуш", "дела"})
    assert find_best_segmentation("боцушдела", dictionary) is None


def test_empty_dictionary_is_a_no_op():
    corrector = WordSegmentationFix()
    ctx = _ctx(frozenset())

    result = corrector.apply("боцушэрнаарахь", ctx)

    assert result.text == "боцушэрнаарахь"
    assert result.corrections == []


def test_very_long_token_is_skipped_for_performance():
    long_garbage = "а" * 40
    dictionary = frozenset({"а" * 40})  # even if "valid", exceeds MAX_TOKEN_LENGTH
    assert find_best_segmentation(long_garbage, dictionary) is None
