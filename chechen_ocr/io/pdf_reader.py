"""
pdf_reader.py

Input support for scanned PDFs, by treating a PDF as "just another way
to package the same photographed pages this project already handles" --
no attempt is made to detect or extract an embedded text layer. In
this project's actual domain (phone photos of a Chechen book, some
scanning apps bundle those photos into a PDF instead of separate JPGs)
a PDF with a real, correct-palochka text layer essentially never
happens: if the text layer were already correct, the whole correction
pipeline wouldn't be needed. So every page is rasterized to an image
and run through the same OcrEngine used for standalone JPG/PNG input
-- one code path, no text-layer-detection branch to maintain.

Requires the `pdf2image` package plus the system `poppler-utils`
binaries (`pdftoppm`/`pdftocairo`) -- these are NOT bundled with the
Python package and must be installed separately (e.g. `apt install
poppler-utils` / `brew install poppler`).

Before rasterizing, check_pdf_safety() (see security.py) verifies file
size and page count via pdf2image.pdfinfo_from_path (metadata only --
no page is rendered for this check), and the actual rasterization call
is bounded by Settings.pdf_render_timeout_seconds. Together these
protect against an oversized or pathologically slow/malicious PDF
hanging or exhausting memory on a batch job.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from ..config import Settings
from ..ocr.base import OcrEngine
from ..ocr.errors import OcrEngineError
from ..security import check_pdf_safety

logger = logging.getLogger(__name__)

DEFAULT_DPI = 300


def process_pdf_pages(
    pdf_path: Path,
    ocr_engine: OcrEngine,
    lang: str = "rus",
    dpi: int = DEFAULT_DPI,
    settings: Settings | None = None,
) -> str:
    """
    Rasterizes every page of `pdf_path` and runs `ocr_engine.recognize()`
    on each, returning one combined text with the same
    "===== Страница N | <source> =====" service-header format that
    ChechenOcrProcessor.process_text() already knows to protect from
    correction and suspicious-word detection.

    Rendered page images are written to a temporary directory that is
    cleaned up automatically -- callers only ever see the final text.
    """
    try:
        from pdf2image import convert_from_path
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "process_pdf_pages requires 'pdf2image' plus the system "
            "poppler-utils binaries (pdftoppm/pdftocairo). "
            "Install with: pip install pdf2image, and "
            "apt install poppler-utils (or brew install poppler)."
        ) from exc

    settings = settings or Settings.default()
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    page_count = check_pdf_safety(
        pdf_path,
        max_pages=settings.max_pdf_pages,
        max_file_size_bytes=settings.max_pdf_file_size_bytes,
    )

    logger.info(
        "rasterizing %s at %d DPI (%d pages, timeout=%ds)",
        pdf_path,
        dpi,
        page_count,
        settings.pdf_render_timeout_seconds,
    )

    try:
        images = convert_from_path(
            str(pdf_path), dpi=dpi, timeout=settings.pdf_render_timeout_seconds
        )
    except Exception as exc:
        raise OcrEngineError(
            "pdf_rasterizer", f"could not rasterize {pdf_path}: {exc}", cause=exc
        ) from exc

    logger.info("%s has %d page(s)", pdf_path, len(images))

    sections: list[str] = []

    with tempfile.TemporaryDirectory(prefix="chechen_ocr_pdf_") as tmp_dir:
        tmp_path = Path(tmp_dir)

        for i, image in enumerate(images, start=1):
            page_image_path = tmp_path / f"page_{i:04d}.png"
            image.save(page_image_path, format="PNG")

            logger.debug("running OCR (%s) on PDF page %d/%d", ocr_engine.name, i, len(images))
            result = ocr_engine.recognize(page_image_path, lang=lang)

            source_label = f"{pdf_path.stem}_page{i:04d}.png"
            header = f"===== Страница {i} | {source_label} ====="
            sections.append(f"{header}\n\n{result.text}\n")

    return "\n".join(sections)
