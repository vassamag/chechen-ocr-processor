from chechen_ocr.config import Settings
from chechen_ocr.core import PipelineContext
from chechen_ocr.correctors.internal_capitalization_fix import InternalCapitalizationFix
from chechen_ocr.dictionaries import Dictionaries


def _ctx() -> PipelineContext:
    return PipelineContext(settings=Settings.default(), dictionaries=Dictionaries.empty())


def test_fixes_capital_letter_mid_word():
    corrector = InternalCapitalizationFix()
    ctx = _ctx()

    result = corrector.apply("ГергШ", ctx)

    assert result.text == "Гергш"
    assert result.corrections[0].rule == "internal_capitalization_fix"


def test_fixes_capital_letter_at_word_end():
    corrector = InternalCapitalizationFix()
    ctx = _ctx()

    result = corrector.apply("веШан", ctx)

    assert result.text == "вешан"


def test_leaves_word_initial_capital_untouched():
    corrector = InternalCapitalizationFix()
    ctx = _ctx()

    result = corrector.apply("Нохчийчоь", ctx)

    assert result.text == "Нохчийчоь"
    assert result.corrections == []


def test_leaves_fully_uppercase_word_untouched():
    # A title/heading in all caps -- not a case error.
    corrector = InternalCapitalizationFix()
    ctx = _ctx()

    result = corrector.apply("БУЬЙСАНАШ", ctx)

    assert result.text == "БУЬЙСАНАШ"
    assert result.corrections == []


def test_leaves_capital_right_after_hyphen_untouched():
    # Second half of a hyphenated compound proper noun -- legitimate
    # capitalization, not an error.
    corrector = InternalCapitalizationFix()
    ctx = _ctx()

    result = corrector.apply("Муса-Паша", ctx)

    assert result.text == "Муса-Паша"
    assert result.corrections == []


def test_palochka_never_touched_regardless_of_position():
    corrector = InternalCapitalizationFix()
    ctx = _ctx()

    result = corrector.apply("тӀахьхало", ctx)

    assert result.text == "тӀахьхало"
    assert result.corrections == []


def test_fixes_multiple_scattered_capitals_in_one_word():
    corrector = InternalCapitalizationFix()
    ctx = _ctx()

    result = corrector.apply("хьУЛУра", ctx)

    assert result.text == "хьулура"


def test_multiple_words_in_text_each_fixed_independently():
    corrector = InternalCapitalizationFix()
    ctx = _ctx()

    result = corrector.apply("Нохчийчоь боШуш дела", ctx)

    assert result.text == "Нохчийчоь бошуш дела"
    assert len(result.corrections) == 1
