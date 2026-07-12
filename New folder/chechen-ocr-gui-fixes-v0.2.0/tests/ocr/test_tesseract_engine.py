import pytest

from chechen_ocr.ocr.errors import OcrEngineError
from chechen_ocr.ocr.tesseract_engine import TesseractEngine


def test_missing_image_raises_ocr_engine_error(tmp_path):
    engine = TesseractEngine()

    with pytest.raises(OcrEngineError) as excinfo:
        engine.recognize(tmp_path / "does_not_exist.jpg")

    assert excinfo.value.engine_name == "tesseract"
    assert excinfo.value.cause is not None


def test_corrupt_image_raises_ocr_engine_error(tmp_path):
    bad_image = tmp_path / "corrupt.jpg"
    bad_image.write_bytes(b"this is not a real image file")
    engine = TesseractEngine()

    with pytest.raises(OcrEngineError) as excinfo:
        engine.recognize(bad_image)

    assert excinfo.value.engine_name == "tesseract"
