from chechen_ocr.correctors.palochka_direct import DirectPalochkaLookalikes


def test_replaces_all_direct_lookalikes(ctx_factory, tiny_dictionaries):
    corrector = DirectPalochkaLookalikes()
    ctx = ctx_factory(tiny_dictionaries)

    result = corrector.apply("Іабо ібадат кӏант", ctx)

    assert result.text == "Ӏабо Ӏбадат кӀант"
    assert {c.rule for c in result.corrections} == {"palochka_direct"}


def test_no_op_on_clean_text(ctx_factory, tiny_dictionaries):
    corrector = DirectPalochkaLookalikes()
    ctx = ctx_factory(tiny_dictionaries)

    result = corrector.apply("хӀара кӀант", ctx)

    assert result.text == "хӀара кӀант"
    assert result.corrections == []
