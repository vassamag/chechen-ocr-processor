from chechen_ocr.correctors.dictionary_candidate import (
    SingleCandidateDictionaryFix,
    generate_palochka_candidates,
    preserve_case,
    split_token,
)


def test_auto_corrects_when_exactly_one_candidate_in_dictionary(ctx_factory, tiny_dictionaries):
    corrector = SingleCandidateDictionaryFix()
    ctx = ctx_factory(tiny_dictionaries)

    result = corrector.apply("кТант", ctx)

    assert result.text == "кӀант"
    assert result.corrections[0].rule == "dictionary_single_candidate"


def test_does_not_guess_when_multiple_candidates_match(ctx_factory, ambiguous_dictionaries):
    corrector = SingleCandidateDictionaryFix()
    ctx = ctx_factory(ambiguous_dictionaries)

    result = corrector.apply("к1а]н", ctx)

    # Both "кӀа]н" and "к1аӀн" are valid dictionary words -> ambiguous -> untouched.
    assert result.text == "к1а]н"
    assert result.corrections == []


def test_leaves_word_unchanged_if_no_candidate_matches(ctx_factory, tiny_dictionaries):
    corrector = SingleCandidateDictionaryFix()
    ctx = ctx_factory(tiny_dictionaries)

    result = corrector.apply("zzz1zzz", ctx)

    assert result.text == "zzz1zzz"
    assert result.corrections == []


def test_pure_numbers_are_never_touched(ctx_factory, tiny_dictionaries):
    corrector = SingleCandidateDictionaryFix()
    ctx = ctx_factory(tiny_dictionaries)

    result = corrector.apply("111", ctx)

    assert result.text == "111"
    assert result.corrections == []


def test_already_valid_dictionary_word_is_left_alone(ctx_factory, tiny_dictionaries):
    corrector = SingleCandidateDictionaryFix()
    ctx = ctx_factory(tiny_dictionaries)

    result = corrector.apply("хӀара", ctx)

    assert result.text == "хӀара"
    assert result.corrections == []


def test_empty_dictionary_is_a_no_op(ctx_factory):
    from chechen_ocr.dictionaries import Dictionaries

    corrector = SingleCandidateDictionaryFix()
    ctx = ctx_factory(Dictionaries.empty())

    result = corrector.apply("кТант", ctx)

    assert result.text == "кТант"
    assert result.corrections == []


def test_case_is_preserved_on_correction():
    assert preserve_case("КТАНТ", "кӀант") == "КӀАНТ"
    assert preserve_case("Кта", "кӀа") == "КӀа"
    assert preserve_case("кта", "кӀа") == "кӀа"


def test_split_token_separates_punctuation():
    assert split_token('"кТант,') == ('"', "кТант", ",")
    assert split_token("кТант") == ("", "кТант", "")


def test_generate_candidates_includes_single_char_and_pair_forms():
    candidates = generate_palochka_candidates("кТант")
    assert "кӀант" in candidates
