from chechen_ocr.correctors.remaining_chars import RemainingCharsCleanup


def test_bang_between_cyrillic_letters_becomes_palochka(ctx_factory, tiny_dictionaries):
    corrector = RemainingCharsCleanup()
    ctx = ctx_factory(tiny_dictionaries)

    result = corrector.apply("х!окху", ctx)

    assert result.text == "хӀокху"


def test_real_punctuation_bang_is_not_touched(ctx_factory, tiny_dictionaries):
    corrector = RemainingCharsCleanup()
    ctx = ctx_factory(tiny_dictionaries)

    result = corrector.apply("Марша вогӀийла!", ctx)

    assert result.text == "Марша вогӀийла!"


def test_final_whitelisted_stem_bang_becomes_palochka(ctx_factory, tiny_dictionaries):
    corrector = RemainingCharsCleanup()
    ctx = ctx_factory(tiny_dictionaries)

    result = corrector.apply("йо!", ctx)

    assert result.text == "йоӀ"


def test_yi_variant_inside_cyrillic_token_is_replaced(ctx_factory, tiny_dictionaries):
    corrector = RemainingCharsCleanup()
    ctx = ctx_factory(tiny_dictionaries)

    result = corrector.apply("ЮьхыШаьржа" + "ї" + "хь", ctx)

    assert "Ӏ" in result.text
    assert "ї" not in result.text


def test_isolated_bracket_near_cyrillic_is_removed(ctx_factory, tiny_dictionaries):
    corrector = RemainingCharsCleanup()
    ctx = ctx_factory(tiny_dictionaries)

    result = corrector.apply("дела ] хӀара", ctx)

    assert "]" not in result.text


def test_pipe_character_is_never_touched(ctx_factory, tiny_dictionaries):
    corrector = RemainingCharsCleanup()
    ctx = ctx_factory(tiny_dictionaries)

    text = "===== Страница 11 | IMG-20250825.jpg ====="
    result = corrector.apply(text, ctx)

    assert "|" in result.text
