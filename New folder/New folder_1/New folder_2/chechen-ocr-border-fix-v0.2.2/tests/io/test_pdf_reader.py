import pytest

from chechen_ocr.io.pdf_reader import process_pdf_pages
from chechen_ocr.ocr.base import OcrResult


class _FakeOcrEngine:
    """Returns a distinct, deterministic 'recognized text' per call,
    based on how many times it's been invoked -- lets tests assert
    that each PDF page really got its own OCR call, in order."""

    name = "fake_ocr"

    def __init__(self):
        self.calls = []

    def recognize(self, image_path, lang="rus"):
        self.calls.append(image_path)
        return OcrResult(text=f"recognized text #{len(self.calls)}", engine_name=self.name)


def _make_single_page_pdf(tmp_path, text="hello"):
    from PIL import Image, ImageDraw

    pdf_path = tmp_path / "single_page.pdf"
    img = Image.new("RGB", (400, 200), color="white")
    draw = ImageDraw.Draw(img)
    draw.text((10, 10), text, fill="black")
    img.save(pdf_path, "PDF")
    return pdf_path


def _make_multi_page_pdf(tmp_path, n_pages=3):
    from PIL import Image, ImageDraw

    pdf_path = tmp_path / "multi_page.pdf"
    pages = []
    for i in range(n_pages):
        img = Image.new("RGB", (400, 200), color="white")
        draw = ImageDraw.Draw(img)
        draw.text((10, 10), f"page {i + 1}", fill="black")
        pages.append(img)
    pages[0].save(pdf_path, "PDF", save_all=True, append_images=pages[1:])
    return pdf_path


def test_missing_pdf_raises_file_not_found(tmp_path):
    engine = _FakeOcrEngine()
    with pytest.raises(FileNotFoundError):
        process_pdf_pages(tmp_path / "does_not_exist.pdf", ocr_engine=engine)


def test_single_page_pdf_produces_one_ocr_call(tmp_path):
    pdf_path = _make_single_page_pdf(tmp_path)
    engine = _FakeOcrEngine()

    text = process_pdf_pages(pdf_path, ocr_engine=engine, dpi=100)

    assert len(engine.calls) == 1
    assert "recognized text #1" in text


def test_multi_page_pdf_produces_one_ocr_call_per_page_in_order(tmp_path):
    pdf_path = _make_multi_page_pdf(tmp_path, n_pages=3)
    engine = _FakeOcrEngine()

    text = process_pdf_pages(pdf_path, ocr_engine=engine, dpi=100)

    assert len(engine.calls) == 3
    # Results should appear in page order.
    assert text.index("recognized text #1") < text.index("recognized text #2")
    assert text.index("recognized text #2") < text.index("recognized text #3")


def test_output_has_page_markers_that_process_text_would_protect(tmp_path):
    from chechen_ocr.processor import is_protected_service_line

    pdf_path = _make_multi_page_pdf(tmp_path, n_pages=2)
    engine = _FakeOcrEngine()

    text = process_pdf_pages(pdf_path, ocr_engine=engine, dpi=100)

    marker_lines = [line for line in text.splitlines() if line.startswith("=====")]
    assert len(marker_lines) == 2
    for line in marker_lines:
        assert is_protected_service_line(line)


def test_page_images_are_cleaned_up_after_processing(tmp_path):
    pdf_path = _make_single_page_pdf(tmp_path)
    engine = _FakeOcrEngine()

    process_pdf_pages(pdf_path, ocr_engine=engine, dpi=100)

    # The temp directory used internally must not leave files behind.
    called_path = engine.calls[0]
    assert not called_path.exists()


def test_rejects_pdf_exceeding_page_limit(tmp_path):
    from chechen_ocr.config import Settings
    from chechen_ocr.security import UnsafeFileError

    pdf_path = _make_multi_page_pdf(tmp_path, n_pages=3)
    engine = _FakeOcrEngine()
    settings = Settings(max_pdf_pages=2)

    with pytest.raises(UnsafeFileError, match="pages, exceeding"):
        process_pdf_pages(pdf_path, ocr_engine=engine, dpi=100, settings=settings)

    assert engine.calls == []  # must fail before any OCR call is made


def test_rejects_pdf_exceeding_file_size_limit(tmp_path):
    from chechen_ocr.config import Settings
    from chechen_ocr.security import UnsafeFileError

    pdf_path = _make_single_page_pdf(tmp_path)
    engine = _FakeOcrEngine()
    settings = Settings(max_pdf_file_size_bytes=10)

    with pytest.raises(UnsafeFileError, match="exceeding"):
        process_pdf_pages(pdf_path, ocr_engine=engine, dpi=100, settings=settings)

    assert engine.calls == []
