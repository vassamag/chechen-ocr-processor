from chechen_ocr.correctors.common_words import CommonWordFixList


def test_known_word_is_corrected(ctx_factory, tiny_dictionaries):
    corrector = CommonWordFixList()
    ctx = ctx_factory(tiny_dictionaries)

    result = corrector.apply("Ша хТара дела.", ctx)

    assert result.text == "Ша хӀара дела."
    assert result.corrections[0].before == "хТара"
    assert result.corrections[0].after == "хӀара"


def test_longer_key_applied_before_shorter_prefix():
    # "хГокхуьнгахь" (longer) must win over "хГокху" (its prefix)
    # so replacements should never leave a broken partial substitution.
    corrector = CommonWordFixList()
    from chechen_ocr.config import Settings
    from chechen_ocr.core import PipelineContext
    from chechen_ocr.dictionaries import Dictionaries

    ctx = PipelineContext(settings=Settings.default(), dictionaries=Dictionaries.empty())
    result = corrector.apply("хГокхуьнгахь", ctx)

    assert result.text == "хӀокхуьнгахь"


def test_custom_fix_map_overrides_default():
    corrector = CommonWordFixList(fixes={"foo": "bar"})
    from chechen_ocr.config import Settings
    from chechen_ocr.core import PipelineContext
    from chechen_ocr.dictionaries import Dictionaries

    ctx = PipelineContext(settings=Settings.default(), dictionaries=Dictionaries.empty())
    result = corrector.apply("foo baz", ctx)

    assert result.text == "bar baz"
