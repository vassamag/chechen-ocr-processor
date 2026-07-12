from chechen_ocr.config import Settings
from chechen_ocr.core import PipelineContext
from chechen_ocr.correctors.general_word_fix import GeneralWordFix, generate_confusion_candidates
from chechen_ocr.dictionaries import Dictionaries


def _ctx(chechen_words: frozenset[str]) -> PipelineContext:
    return PipelineContext(
        settings=Settings.default(),
        dictionaries=Dictionaries(chechen_words=chechen_words),
    )


def test_corrects_yer_confusion_when_unique_match():
    corrector = GeneralWordFix()
    ctx = _ctx(frozenset({"аьрзу"}))

    result = corrector.apply("Аързу ву ца", ctx)

    assert result.text == "Аьрзу ву ца"
    assert result.corrections[0].rule == "general_word_fix"


def test_corrects_za_a_confusion():
    corrector = GeneralWordFix()
    ctx = _ctx(frozenset({"охьакхачаран"}))

    result = corrector.apply("охьзкхачаран дела", ctx)

    assert result.text == "охьакхачаран дела"


def test_corrects_ha_kha_confusion():
    corrector = GeneralWordFix()
    ctx = _ctx(frozenset({"кхузахь"}))

    result = corrector.apply("кҳузахь дела", ctx)

    assert result.text == "кхузахь дела"


def test_does_not_touch_already_valid_word():
    corrector = GeneralWordFix()
    ctx = _ctx(frozenset({"хьара"}))

    result = corrector.apply("хьара дела", ctx)

    assert result.text == "хьара дела"
    assert result.corrections == []


def test_no_op_when_no_candidate_matches():
    corrector = GeneralWordFix()
    ctx = _ctx(frozenset({"somethingelse"}))

    result = corrector.apply("Аързу ву", ctx)

    assert result.text == "Аързу ву"
    assert result.corrections == []


def test_ambiguous_when_multiple_candidates_match():
    # Word has both 'ъ' and 'з', each substitutable -- if BOTH
    # resulting candidates are valid dictionary words, don't guess.
    corrector = GeneralWordFix()
    ctx = _ctx(frozenset({"тьзт", "тъат"}))  # both candidates for "тъзт"

    result = corrector.apply("тъзт дела", ctx)

    assert result.text == "тъзт дела"
    assert result.corrections == []


def test_empty_dictionary_is_a_no_op():
    corrector = GeneralWordFix()
    ctx = _ctx(frozenset())

    result = corrector.apply("Аързу ву", ctx)

    assert result.text == "Аързу ву"
    assert result.corrections == []


def test_generate_confusion_candidates_single_pair():
    candidates = generate_confusion_candidates("аързу")
    assert "аьрзу" in candidates


def test_corrects_av_ah_confusion():
    # Raised via project discussion: OCR sometimes turns ь into в
    # specifically after а (the "аь" digraph), independently of the
    # already-known ъ/ь confusion. Verified against real raw OCR text
    # in the project's own golden corpus (29 clean, unambiguous
    # matches) before being added here.
    corrector = GeneralWordFix()
    ctx = _ctx(frozenset({"лаьттачу"}))

    result = corrector.apply("лавттачу дела", ctx)

    assert result.text == "лаьттачу дела"


def test_corrects_ay_ah_confusion():
    # Same family of finding as the ав/аь pair, raised separately via
    # project discussion: OCR sometimes turns ь into ы after а. Rarer
    # in practice (4 clean matches vs. 29 for ав/аь on the same
    # corpus) but still a real, unambiguous pattern.
    corrector = GeneralWordFix()
    ctx = _ctx(frozenset({"маьна"}))

    result = corrector.apply("маына дела", ctx)

    assert result.text == "маьна дела"
