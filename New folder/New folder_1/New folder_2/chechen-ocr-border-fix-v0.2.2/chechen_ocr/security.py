"""
security.py

Safety checks for DOCX and PDF input, both of which are compound/
archive formats that a naive reader ends up trusting unconditionally.
This matters once files can come from someone other than the project
owner (a reviewer, a contributor, anyone submitting a scan for
processing) rather than only ever being files the owner personally
created.

Two distinct threats are addressed:

1. Resource exhaustion via a "zip bomb": a DOCX is a ZIP archive.
   A small file can be crafted to decompress to gigabytes (or more) of
   data, exhausting memory/disk when a naive reader (e.g. python-docx)
   extracts it. check_docx_zip_safety() inspects the archive's entry
   metadata (sizes are stored in the zip's central directory) WITHOUT
   decompressing anything, and rejects the file if it looks like a bomb
   before python-docx ever touches it.

2. Resource exhaustion via a huge/malicious PDF: an enormous page
   count, or a PDF crafted to make rendering pathologically slow, can
   hang or exhaust memory in the rasterization step. check_pdf_safety()
   checks the file size and page count (via pdf2image.pdfinfo_from_path,
   which reads PDF metadata without rendering any page) before
   rasterizing, and the caller (io/pdf_reader.py) applies a timeout to
   the actual rendering call.

These are deliberately simple, dependency-light checks -- not a full
sandboxed file-format parser. They raise before the expensive/risky
operation, they don't try to sanitize or repair a suspicious file.
"""

from __future__ import annotations

import zipfile
from pathlib import Path


class UnsafeFileError(Exception):
    """Raised when an input file fails a safety check before parsing."""


def check_file_size(path: Path, max_bytes: int, label: str = "file") -> None:
    size = path.stat().st_size
    if size > max_bytes:
        raise UnsafeFileError(
            f"{label} {path.name} is {size:,} bytes, exceeding the "
            f"{max_bytes:,}-byte limit. Raise the relevant Settings "
            f"limit if this file is legitimately this large."
        )


def check_docx_zip_safety(
    path: Path,
    max_uncompressed_bytes: int,
    max_compression_ratio: float,
    max_entry_count: int,
) -> None:
    """
    Inspects a DOCX's ZIP central directory (cheap: no decompression)
    and rejects it if it looks like a zip bomb:

    - total uncompressed size across all entries exceeds
      max_uncompressed_bytes, or
    - any single entry's compression ratio (uncompressed / compressed)
      exceeds max_compression_ratio (ordinary XML-based DOCX content
      typically compresses 5-15x; ratios in the hundreds or thousands
      are a bomb signature), or
    - the archive has an implausible number of entries for a document
      (max_entry_count).

    Raises UnsafeFileError if any check fails, or if the file isn't a
    readable ZIP archive at all (a DOCX must be one).
    """
    try:
        with zipfile.ZipFile(path) as zf:
            infos = zf.infolist()
    except zipfile.BadZipFile as exc:
        raise UnsafeFileError(
            f"{path.name} is not a valid DOCX (not a readable ZIP archive)"
        ) from exc

    if len(infos) > max_entry_count:
        raise UnsafeFileError(
            f"{path.name} has {len(infos)} zip entries, exceeding the "
            f"{max_entry_count}-entry limit for a plausible DOCX"
        )

    total_uncompressed = 0
    for info in infos:
        total_uncompressed += info.file_size

        if info.compress_size > 0:
            ratio = info.file_size / info.compress_size
            if ratio > max_compression_ratio:
                raise UnsafeFileError(
                    f"{path.name}: entry {info.filename!r} has a "
                    f"{ratio:.0f}x compression ratio, exceeding the "
                    f"{max_compression_ratio:.0f}x limit -- looks like a zip bomb"
                )

    if total_uncompressed > max_uncompressed_bytes:
        raise UnsafeFileError(
            f"{path.name} would decompress to {total_uncompressed:,} bytes, "
            f"exceeding the {max_uncompressed_bytes:,}-byte limit"
        )


def check_pdf_safety(path: Path, max_pages: int, max_file_size_bytes: int) -> int:
    """
    Checks file size and, via pdf2image.pdfinfo_from_path (reads PDF
    metadata only -- does not render any page), the page count.
    Returns the page count on success, for the caller's convenience
    (e.g. to log it, or pass first_page/last_page bounds explicitly to
    convert_from_path rather than relying on it re-deriving the count).

    Raises UnsafeFileError if either limit is exceeded, or if pdfinfo
    can't read the file at all (encrypted/corrupt PDF).
    """
    check_file_size(path, max_file_size_bytes, label="PDF")

    from pdf2image import pdfinfo_from_path
    from pdf2image.exceptions import PDFPageCountError

    try:
        info = pdfinfo_from_path(str(path))
    except PDFPageCountError as exc:
        raise UnsafeFileError(f"could not read page count for {path.name}: {exc}") from exc

    pages_raw = info.get("Pages")
    if pages_raw is None:
        raise UnsafeFileError(f"could not determine page count for {path.name}")
    pages = int(pages_raw)

    if pages > max_pages:
        raise UnsafeFileError(
            f"{path.name} has {pages} pages, exceeding the {max_pages}-page "
            f"limit. Raise Settings.max_pdf_pages if this is legitimate, or "
            f"split the PDF first."
        )

    return pages
