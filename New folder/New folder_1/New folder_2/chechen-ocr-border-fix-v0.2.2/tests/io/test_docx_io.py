from docx import Document

from chechen_ocr.io.docx_reader import extract_docx_to_text
from chechen_ocr.io.docx_writer import save_docx


def test_save_and_read_back_roundtrip(tmp_path):
    path = tmp_path / "out.docx"
    text = "Цхьа стаг вара.\nВукхо дийцира цунна."

    save_docx(text, path)
    result = extract_docx_to_text(path)

    assert result == text


def test_suspicious_words_get_highlighted(tmp_path):
    path = tmp_path / "out.docx"
    text = "Цхьа Аълбикин хилла."

    save_docx(text, path, suspicious_words=["Аълбикин"])

    document = Document(str(path))
    highlighted_runs = [
        run.text
        for paragraph in document.paragraphs
        for run in paragraph.runs
        if run.font.highlight_color is not None
    ]

    assert "Аълбикин" in highlighted_runs


def test_non_suspicious_words_are_not_highlighted(tmp_path):
    path = tmp_path / "out.docx"
    text = "Цхьа стаг вара."

    save_docx(text, path, suspicious_words=["Аълбикин"])

    document = Document(str(path))
    highlighted_runs = [
        run.text
        for paragraph in document.paragraphs
        for run in paragraph.runs
        if run.font.highlight_color is not None
    ]

    assert highlighted_runs == []


def test_extract_reads_table_content(tmp_path):
    path = tmp_path / "with_table.docx"
    document = Document()
    document.add_paragraph("Intro text")
    table = document.add_table(rows=1, cols=2)
    table.rows[0].cells[0].text = "cell one"
    table.rows[0].cells[1].text = "cell two"
    document.save(str(path))

    result = extract_docx_to_text(path)

    assert "Intro text" in result
    assert "cell one\tcell two" in result


def test_extract_rejects_oversized_docx(tmp_path):
    import pytest

    from chechen_ocr.config import Settings
    from chechen_ocr.security import UnsafeFileError

    path = tmp_path / "normal.docx"
    document = Document()
    document.add_paragraph("Цхьа стаг вара.")
    document.save(str(path))

    settings = Settings(max_docx_file_size_bytes=10)  # smaller than any real docx
    with pytest.raises(UnsafeFileError):
        extract_docx_to_text(path, settings=settings)


def test_extract_rejects_non_zip_docx(tmp_path):
    import pytest

    from chechen_ocr.security import UnsafeFileError

    path = tmp_path / "fake.docx"
    path.write_bytes(b"not a real docx file")

    with pytest.raises(UnsafeFileError):
        extract_docx_to_text(path)
