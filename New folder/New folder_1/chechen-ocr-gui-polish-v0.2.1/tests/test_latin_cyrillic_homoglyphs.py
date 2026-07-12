from chechen_ocr.config import Settings
from chechen_ocr.core import PipelineContext
from chechen_ocr.correctors.latin_cyrillic_homoglyphs import LatinCyrillicHomoglyphFix
from chechen_ocr.dictionaries import Dictionaries


def _ctx() -> PipelineContext:
    return PipelineContext(settings=Settings.default(), dictionaries=Dictionaries.empty())


def test_fixes_single_latin_letter_mixed_into_cyrillic_word():
    corrector = LatinCyrillicHomoglyphFix()
    ctx = _ctx()

    # Trailing "a" here is Latin (U+0061), the rest of the word is Cyrillic.
    result = corrector.apply("цхаьцца" + "a", ctx)

    assert result.text == "цхаьццаа"
    assert result.corrections[0].rule == "latin_cyrillic_homoglyph_fix"


def test_fixes_multiple_latin_letters_in_one_word():
    corrector = LatinCyrillicHomoglyphFix()
    ctx = _ctx()

    # "кeрлaчу" -- Latin e, a mixed into an otherwise-Cyrillic word.
    word = "к" + "e" + "рл" + "a" + "чу"
    result = corrector.apply(word, ctx)

    assert result.text == "керлачу"


def test_leaves_pure_latin_word_untouched():
    corrector = LatinCyrillicHomoglyphFix()
    ctx = _ctx()

    result = corrector.apply("Hello world", ctx)

    assert result.text == "Hello world"
    assert result.corrections == []


def test_leaves_pure_cyrillic_word_untouched():
    corrector = LatinCyrillicHomoglyphFix()
    ctx = _ctx()

    result = corrector.apply("керлачу дела", ctx)

    assert result.text == "керлачу дела"
    assert result.corrections == []


def test_leaves_roman_numeral_untouched():
    # "IV" has no unambiguous Cyrillic letter at all -- must not be
    # "fixed" into something else just because I/V have Cyrillic
    # look-alikes in some other alphabets.
    corrector = LatinCyrillicHomoglyphFix()
    ctx = _ctx()

    result = corrector.apply("Глава IV", ctx)

    assert result.text == "Глава IV"
    assert result.corrections == []


def test_fixes_lowercase_latin_l_to_palochka_unconditionally():
    # Found via project discussion, same family as I/i/1: after
    # fixing those, "l" turned out to be the single largest remaining
    # source of "mixed Latin/Cyrillic" flags on real book data.
    corrector = LatinCyrillicHomoglyphFix()
    ctx = _ctx()

    result = corrector.apply("Т" + "l" + "ахьхало", ctx)

    assert result.text == "ТӀахьхало"
    assert result.corrections[0].rule == "latin_cyrillic_homoglyph_fix"


def test_uppercase_latin_L_still_untouched():
    # Capital "L" is deliberately NOT included -- comparatively rare
    # and less clearly always-wrong in the data actually checked than
    # its lowercase form.
    corrector = LatinCyrillicHomoglyphFix()
    ctx = _ctx()

    word = "к" + "L" + "ант"
    result = corrector.apply(word, ctx)

    assert result.text == word
    assert result.corrections == []


def test_fixes_word_internal_digit_one_to_palochka():
    corrector = LatinCyrillicHomoglyphFix()
    ctx = _ctx()

    result = corrector.apply("к" + "1" + "ант", ctx)

    assert result.text == "кӀант"
    assert result.corrections[0].rule == "latin_cyrillic_homoglyph_fix"


def test_fixes_word_initial_digit_one_to_palochka():
    corrector = LatinCyrillicHomoglyphFix()
    ctx = _ctx()

    result = corrector.apply("1" + "оьтарна", ctx)

    assert result.text == "Ӏоьтарна"


def test_fixes_word_final_digit_one_to_palochka():
    corrector = LatinCyrillicHomoglyphFix()
    ctx = _ctx()

    result = corrector.apply("дац" + "1", ctx)

    assert result.text == "дацӀ"


def test_standalone_multi_digit_number_untouched():
    # A genuine year/quantity -- no letters at all in the token, so
    # the core safety guard leaves it alone.
    corrector = LatinCyrillicHomoglyphFix()
    ctx = _ctx()

    result = corrector.apply("в " + "2014" + " году", ctx)

    assert "2014" in result.text
    assert result.corrections == []


def test_multi_digit_number_protected_even_when_glued_to_cyrillic():
    # Pathological but important: even if a multi-digit number ends up
    # glued to Cyrillic text for some other reason, only an ISOLATED
    # "1" gets touched -- "2014" itself must survive intact.
    corrector = LatinCyrillicHomoglyphFix()
    ctx = _ctx()

    result = corrector.apply("2014" + "года", ctx)

    assert "2014" in result.text
    assert "года" in result.text


def test_fixes_capital_latin_I_to_palochka_unconditionally():
    # The actual case raised via project discussion: capital Latin "I"
    # generated in place of the palochka by the Vision API, with no
    # dictionary-verified candidate available for many word forms
    # (which is why SingleCandidateDictionaryFix alone left the
    # majority of these flagged rather than fixed). This corrector
    # doesn't need a dictionary at all -- genuine Latin "I" essentially
    # never appears inside a Cyrillic Chechen word.
    corrector = LatinCyrillicHomoglyphFix()
    ctx = _ctx()

    result = corrector.apply("Ц" + "I" + "ацхоьу", ctx)

    assert result.text == "ЦӀацхоьу"
    assert result.corrections[0].rule == "latin_cyrillic_homoglyph_fix"


def test_fixes_lowercase_latin_i_to_palochka_unconditionally():
    corrector = LatinCyrillicHomoglyphFix()
    ctx = _ctx()

    result = corrector.apply("д" + "i" + "асахийзара", ctx)

    assert result.text == "дӀасахийзара"


def test_roman_numeral_with_capital_I_still_untouched():
    # Reconfirms the core safety guarantee still holds after adding
    # I/i to the mapping: "III" has no unambiguous Cyrillic letter at
    # all, so it must be left alone even though every character in it
    # is now individually mappable.
    corrector = LatinCyrillicHomoglyphFix()
    ctx = _ctx()

    result = corrector.apply("Глава III", ctx)

    assert result.text == "Глава III"
    assert result.corrections == []


def test_uppercase_homoglyphs_also_fixed():
    corrector = LatinCyrillicHomoglyphFix()
    ctx = _ctx()

    # Latin "H" mixed into an otherwise-Cyrillic capitalized word.
    word = "H" + "охчийн"
    result = corrector.apply(word, ctx)

    assert result.text == "Нохчийн"


def test_multiple_words_in_one_text_all_fixed():
    corrector = LatinCyrillicHomoglyphFix()
    ctx = _ctx()

    text = "керлачу " + ("хaлкъ") + " кхетош"
    result = corrector.apply(text, ctx)

    assert result.text == "керлачу халкъ кхетош"
    assert len(result.corrections) == 1


def test_fixes_t_k_n_u_homoglyphs():
    corrector = LatinCyrillicHomoglyphFix()
    ctx = _ctx()

    assert corrector.apply("t" + "хо", ctx).text == "тхо"
    assert corrector.apply("ди" + "k" + "ачу", ctx).text == "дикачу"
    assert corrector.apply("ше" + "n", ctx).text == "шен"
    assert corrector.apply("б" + "u" + "ззина", ctx).text == "буззина"
