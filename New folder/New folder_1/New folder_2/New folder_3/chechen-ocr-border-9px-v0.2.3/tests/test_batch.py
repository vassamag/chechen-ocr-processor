import pytest

from chechen_ocr.batch import BatchProcessor, _natural_sort_key
from chechen_ocr.config import Settings
from chechen_ocr.dictionaries import Dictionaries
from chechen_ocr.ocr.base import OcrResult
from chechen_ocr.processor import ChechenOcrProcessor


class _FakeOcrEngine:
    name = "fake_ocr"

    def __init__(self, texts_by_filename):
        self.texts_by_filename = texts_by_filename
        self.calls = []

    def recognize(self, image_path, lang="rus"):
        self.calls.append(image_path.name)
        return OcrResult(text=self.texts_by_filename[image_path.name], engine_name=self.name)


def _make_processor(ocr_engine=None):
    return ChechenOcrProcessor(
        settings=Settings.default(),
        ocr_engine=ocr_engine,
        dictionaries=Dictionaries.empty(),
    )


def test_natural_sort_orders_numbers_correctly():
    from pathlib import Path

    paths = [Path("page10.jpg"), Path("page2.jpg"), Path("page1.jpg")]
    ordered = sorted(paths, key=_natural_sort_key)
    assert [p.name for p in ordered] == ["page1.jpg", "page2.jpg", "page10.jpg"]


def test_process_directory_with_text_files(tmp_path):
    (tmp_path / "page1.txt").write_text("хӀара кӀант дела.", encoding="utf-8")
    (tmp_path / "page2.txt").write_text("хТара текст.", encoding="utf-8")

    processor = _make_processor()
    batch = BatchProcessor(processor)

    result = batch.process_directory(tmp_path)

    assert len(result.per_file) == 2
    assert result.per_file[0].filename == "page1.txt"
    assert result.per_file[1].filename == "page2.txt"
    assert "===== Страница 1 | page1.txt =====" in result.doc.corrected_text
    assert "===== Страница 2 | page2.txt =====" in result.doc.corrected_text
    assert result.skipped_files == []


def test_process_directory_passes_ocr_engine_name_through(tmp_path):
    # A stray capital mid-word is only fixed by InternalCapitalizationFix,
    # which is engine-gated the OPPOSITE way from the Tesseract-specific
    # correctors: it only runs when ocr_engine_name is NOT "tesseract"/None.
    (tmp_path / "page1.txt").write_text("боШуш дела.", encoding="utf-8")

    processor = _make_processor()
    batch = BatchProcessor(processor)

    tesseract_result = batch.process_directory(tmp_path, ocr_engine_name="tesseract")
    vision_result = batch.process_directory(tmp_path, ocr_engine_name="openai_vision")

    assert "боШуш" in tesseract_result.doc.corrected_text  # untouched for Tesseract
    assert "бошуш" in vision_result.doc.corrected_text  # case-fixed for Vision


def test_process_directory_with_images_uses_ocr_engine(tmp_path):
    (tmp_path / "a.jpg").write_bytes(b"fake")
    (tmp_path / "b.jpg").write_bytes(b"fake")

    engine = _FakeOcrEngine({"a.jpg": "хӀара текст а", "b.jpg": "кТант дела б"})
    processor = _make_processor(ocr_engine=engine)
    batch = BatchProcessor(processor)

    result = batch.process_directory(tmp_path)

    assert engine.calls == ["a.jpg", "b.jpg"]
    assert len(result.per_file) == 2


def test_unsupported_extension_raises_when_no_supported_files():
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "notes.md").write_text("nothing usable here")
        processor = _make_processor()
        batch = BatchProcessor(processor)

        with pytest.raises(ValueError, match="No supported files found"):
            batch.process_directory(Path(d))


def test_unreadable_file_is_skipped_not_fatal_by_default(tmp_path):
    (tmp_path / "good.txt").write_text("хӀара дела.", encoding="utf-8")
    (tmp_path / "bad.jpg").write_bytes(b"not a real image")

    # No OCR engine configured -> reading the .jpg will raise; should be
    # skipped rather than aborting the whole batch.
    processor = _make_processor(ocr_engine=None)
    batch = BatchProcessor(processor)

    result = batch.process_directory(tmp_path)

    assert len(result.skipped_files) == 1
    assert result.skipped_files[0][0] == "bad.jpg"
    assert len(result.per_file) == 1
    assert result.per_file[0].filename == "good.txt"


def test_stop_on_error_raises_immediately(tmp_path):
    (tmp_path / "bad.jpg").write_bytes(b"not a real image")

    processor = _make_processor(ocr_engine=None)
    batch = BatchProcessor(processor)

    with pytest.raises(ValueError):
        batch.process_directory(tmp_path, stop_on_error=True)


def test_worst_files_sorted_by_suspicious_ratio(tmp_path):
    (tmp_path / "clean.txt").write_text("хӀара кӀант дела.", encoding="utf-8")
    (tmp_path / "messy.txt").write_text("до[учу фыва[длро секха[ад", encoding="utf-8")

    processor = _make_processor()
    batch = BatchProcessor(processor)

    result = batch.process_directory(tmp_path)
    worst = result.worst_files

    assert worst[0].filename == "messy.txt"


def test_export_writes_expected_files(tmp_path):
    (tmp_path / "page1.txt").write_text("хӀара кӀант дела.", encoding="utf-8")
    output_dir = tmp_path / "output"

    processor = _make_processor()
    batch = BatchProcessor(processor)
    result = batch.process_directory(tmp_path)
    paths = batch.export(result, output_dir, base_name="mybook")

    assert paths["corrected_txt"].exists()
    assert paths["corrections_report"].exists()
    assert paths["review_csv"].exists()
    assert paths["per_file_report"].exists()
    assert "docx" not in paths

    per_file_report = paths["per_file_report"].read_text(encoding="utf-8-sig")
    assert "page1.txt" in per_file_report
