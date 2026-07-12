from chechen_ocr.processor import build_pipeline


def test_tesseract_pipeline_includes_lookalike_correctors():
    pipeline = build_pipeline("tesseract")
    names = pipeline.corrector_names()

    assert "palochka_direct" in names
    assert "palochka_pattern" in names
    assert "common_word_fix" in names
    assert "dictionary_single_candidate" in names
    assert "remaining_chars_cleanup" in names


def test_vision_pipeline_skips_latin_lookalike_correctors():
    pipeline = build_pipeline("openai_vision")
    names = pipeline.corrector_names()

    assert "palochka_direct" not in names
    assert "palochka_pattern" not in names
    assert "common_word_fix" not in names
    # Disambiguation and final cleanup still apply regardless of engine.
    assert "dictionary_single_candidate" in names
    assert "remaining_chars_cleanup" in names


def test_full_pipeline_runs_end_to_end(ctx_factory, tiny_dictionaries):
    pipeline = build_pipeline("tesseract")
    ctx = ctx_factory(tiny_dictionaries)

    raw = "Іабо, г!урбанна кТант, хГара х!окху."
    result = pipeline.run(raw, ctx)

    assert "Ӏабо" in result.text
    assert "гӀурбанна" in result.text
    assert "кӀант" in result.text
    assert "хӀара" in result.text
    assert "хӀокху" in result.text
    assert len(result.corrections) > 0
