"""
Tesseract-based OCR engine.

Replaces the original module-level:

    pytesseract.pytesseract.tesseract_cmd = r"C:\\Program Files\\Tesseract-OCR\\tesseract.exe"

with an explicit, optional constructor argument sourced from
Settings.tesseract_cmd. If not given, pytesseract falls back to
whatever is on PATH (works out of the box on Linux/macOS where
Tesseract is installed via a package manager).

pytesseract/Pillow are only imported lazily inside __init__, so that
importing chechen_ocr.ocr doesn't hard-require them if you only ever
use a Vision-API engine (or process pre-existing text files and never
touch images at all).

Unlike the Vision-API engine, Tesseract runs locally (no network calls,
no rate limits), so most of the retry/backoff machinery in ocr/retry.py
doesn't apply here -- a failure is almost always either "binary not
found" (a setup problem, not transient) or "corrupt/unreadable image"
(retrying won't help). recognize() wraps both into OcrEngineError with
a clear message instead of letting a raw pytesseract/PIL exception
propagate, so callers processing a batch can catch one exception type
regardless of which engine is in use.
"""

from __future__ import annotations

import logging
from pathlib import Path

from .base import OcrResult
from .errors import OcrEngineError

logger = logging.getLogger(__name__)


class TesseractEngine:
    name = "tesseract"

    def __init__(self, tesseract_cmd: str | None = None):
        try:
            import pytesseract
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "TesseractEngine requires 'pytesseract' and 'Pillow'. "
                "Install with: pip install pytesseract Pillow"
            ) from exc

        if tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = tesseract_cmd

        self._pytesseract = pytesseract

    def recognize(self, image_path: Path, lang: str = "rus") -> OcrResult:
        from PIL import Image

        image_path = Path(image_path)

        try:
            image = Image.open(image_path)
        except Exception as exc:
            raise OcrEngineError(
                self.name, f"could not open image {image_path}: {exc}", cause=exc
            ) from exc

        try:
            text = self._pytesseract.image_to_string(image, lang=lang)
        except Exception as exc:
            raise OcrEngineError(
                self.name, f"recognition failed for {image_path}: {exc}", cause=exc
            ) from exc

        logger.info("%s recognized %d chars from %s", self.name, len(text), image_path.name)
        return OcrResult(text=text, engine_name=self.name)
