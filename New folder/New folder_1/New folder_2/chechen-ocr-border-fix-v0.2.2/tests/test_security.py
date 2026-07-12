import zipfile

import pytest
from docx import Document

from chechen_ocr.security import (
    UnsafeFileError,
    check_docx_zip_safety,
    check_file_size,
    check_pdf_safety,
)


def test_check_file_size_passes_under_limit(tmp_path):
    path = tmp_path / "small.txt"
    path.write_bytes(b"x" * 100)
    check_file_size(path, max_bytes=1000)  # should not raise


def test_check_file_size_raises_over_limit(tmp_path):
    path = tmp_path / "big.txt"
    path.write_bytes(b"x" * 1000)
    with pytest.raises(UnsafeFileError, match="exceeding"):
        check_file_size(path, max_bytes=100)


def test_check_docx_zip_safety_passes_for_real_docx(tmp_path):
    path = tmp_path / "normal.docx"
    document = Document()
    document.add_paragraph("Цхьа стаг вара." * 50)
    document.save(str(path))

    check_docx_zip_safety(
        path, max_uncompressed_bytes=10_000_000, max_compression_ratio=100.0, max_entry_count=2000
    )  # should not raise


def test_check_docx_zip_safety_rejects_non_zip_file(tmp_path):
    path = tmp_path / "fake.docx"
    path.write_bytes(b"this is not a zip file at all")

    with pytest.raises(UnsafeFileError, match="not a valid DOCX"):
        check_docx_zip_safety(
            path,
            max_uncompressed_bytes=10_000_000,
            max_compression_ratio=100.0,
            max_entry_count=2000,
        )


def test_check_docx_zip_safety_rejects_zip_bomb_by_ratio(tmp_path):
    # Craft a zip entry that compresses extremely well (highly
    # repetitive data), simulating a zip-bomb-style entry.
    path = tmp_path / "bomb.docx"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("word/document.xml", b"A" * 50_000_000)  # 50MB of one repeated byte

    with pytest.raises(UnsafeFileError, match="compression ratio"):
        check_docx_zip_safety(
            path,
            max_uncompressed_bytes=10_000_000_000,  # high enough that ratio triggers first
            max_compression_ratio=100.0,
            max_entry_count=2000,
        )


def test_check_docx_zip_safety_rejects_by_total_uncompressed_size(tmp_path):
    path = tmp_path / "big_total.docx"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as zf:
        # Low compression ratio (stored, not deflated) but a large
        # total uncompressed size should still be rejected.
        zf.writestr("word/document.xml", b"random-ish content, not repetitive" * 2000)

    with pytest.raises(UnsafeFileError, match="decompress to"):
        check_docx_zip_safety(
            path, max_uncompressed_bytes=1000, max_compression_ratio=1000.0, max_entry_count=2000
        )


def test_check_docx_zip_safety_rejects_too_many_entries(tmp_path):
    path = tmp_path / "many_entries.docx"
    with zipfile.ZipFile(path, "w") as zf:
        for i in range(50):
            zf.writestr(f"file_{i}.xml", b"x")

    with pytest.raises(UnsafeFileError, match="zip entries"):
        check_docx_zip_safety(
            path, max_uncompressed_bytes=10_000_000, max_compression_ratio=100.0, max_entry_count=10
        )


def test_check_pdf_safety_passes_for_small_pdf(tmp_path):
    from PIL import Image

    path = tmp_path / "small.pdf"
    img = Image.new("RGB", (200, 100), color="white")
    img.save(path, "PDF")

    pages = check_pdf_safety(path, max_pages=10, max_file_size_bytes=10_000_000)
    assert pages == 1


def test_check_pdf_safety_rejects_too_many_pages(tmp_path):
    from PIL import Image

    path = tmp_path / "multi.pdf"
    pages = [Image.new("RGB", (200, 100), color="white") for _ in range(5)]
    pages[0].save(path, "PDF", save_all=True, append_images=pages[1:])

    with pytest.raises(UnsafeFileError, match="pages, exceeding"):
        check_pdf_safety(path, max_pages=3, max_file_size_bytes=10_000_000)


def test_check_pdf_safety_rejects_oversized_file(tmp_path):
    from PIL import Image

    path = tmp_path / "small.pdf"
    img = Image.new("RGB", (200, 100), color="white")
    img.save(path, "PDF")

    with pytest.raises(UnsafeFileError, match="exceeding"):
        check_pdf_safety(path, max_pages=10, max_file_size_bytes=10)
