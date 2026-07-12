from chechen_ocr.correctors.palochka_pattern import PatternBasedPalochka


def test_consonant_plus_lookalike_becomes_palochka(ctx_factory, tiny_dictionaries):
    corrector = PatternBasedPalochka()
    ctx = ctx_factory(tiny_dictionaries)

    result = corrector.apply("г!урбанна к1ант х|ара", ctx)

    assert result.text == "гӀурбанна кӀант хӀара"
    assert len(result.corrections) == 3


def test_does_not_touch_non_base_letters(ctx_factory, tiny_dictionaries):
    corrector = PatternBasedPalochka()
    ctx = ctx_factory(tiny_dictionaries)

    # 'с' is not in BASE_LETTERS, so "с1" must be left alone.
    result = corrector.apply("с1ест", ctx)

    assert result.text == "с1ест"
    assert result.corrections == []


def test_position_is_tracked(ctx_factory, tiny_dictionaries):
    corrector = PatternBasedPalochka()
    ctx = ctx_factory(tiny_dictionaries)

    result = corrector.apply("аа т1ест", ctx)

    assert len(result.corrections) == 1
    assert result.corrections[0].position == 3
