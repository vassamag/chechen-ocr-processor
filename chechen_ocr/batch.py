"""
batch.py

Runs the correction pipeline over an entire directory of input files
(a whole scanned book) as ONE connected document, instead of one file
at a time through the CLI. This is the piece that was missing to
actually apply everything else in this package (golden-file tests,
review workflow, metrics) to a real book in a single pass:

    from chechen_ocr import ChechenOcrProcessor, Settings
    from chechen_ocr.ocr import TesseractEngine
    from chechen_ocr.batch import BatchProcessor

    processor = ChechenOcrProcessor(settings=Settings.default(), ocr_engine=TesseractEngine())
    batch = BatchProcessor(processor)

    result = batch.process_directory(Path("scans/"))
    batch.export(result, Path("output/"))

Design: rather than re-implementing correction/suspicious-word
merging logic for "many files", every input file's raw text is
extracted (OCR for images/PDF pages, direct read for TXT, extraction
for DOCX) and wrapped in the same "===== Страница N | <filename> ====="
service header the rest of the package already knows how to protect
from correction (processor.is_protected_service_line) and parse for
page attribution (review.schema.build_page_index). All per-file raw
texts are concatenated into ONE blob and run through
ChechenOcrProcessor.process_text() exactly once -- so correction,
suspicious-word detection, and metrics all behave identically to
processing one giant file, with no separate merging code to maintain
or get out of sync with the single-file path.

Page numbering here is simply the file's position in the sorted
input list (1, 2, 3, ...) -- NOT a recognized printed page number.
Matching photos to printed page numbers (as the original project's
raw OCR dump did) is a separate, harder problem (see the golden-file
harness's manual_resolutions.py for how messy that recognition step
can get) and is out of scope here; the original filename is preserved
in the header for traceability regardless.
"""

from __future__ import annotations

import csv
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from .metrics import DocumentMetrics
from .processor import ChechenOcrProcessor, ProcessedDocument
from .review.schema import build_page_index

logger = logging.getLogger(__name__)

_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".gif"}
_TEXT_EXTENSIONS = {".txt"}
_DOCX_EXTENSIONS = {".docx"}
_PDF_EXTENSIONS = {".pdf"}

SUPPORTED_EXTENSIONS = _IMAGE_EXTENSIONS | _TEXT_EXTENSIONS | _DOCX_EXTENSIONS | _PDF_EXTENSIONS


@dataclass
class BatchFileResult:
    """Per-input-file quality breakdown, sliced out of the combined
    document after the fact using its page markers -- lets a reviewer
    see which specific file most needs attention without opening the
    whole book's output."""

    index: int
    filename: str
    word_count: int
    correction_count: int
    suspicious_count: int

    @property
    def suspicious_ratio(self) -> float:
        return self.suspicious_count / self.word_count if self.word_count else 0.0


@dataclass
class BatchResult:
    doc: ProcessedDocument
    metrics: DocumentMetrics
    per_file: list[BatchFileResult] = field(default_factory=list)
    skipped_files: list[tuple[str, str]] = field(default_factory=list)  # (filename, reason)

    @property
    def worst_files(self) -> list[BatchFileResult]:
        """Per-file results sorted by suspicious_ratio, worst first --
        the files most worth prioritizing for human review."""
        return sorted(self.per_file, key=lambda f: f.suspicious_ratio, reverse=True)


def _natural_sort_key(path: Path) -> tuple:
    """Sorts filenames the way a human expects (page2 before page10),
    not plain lexicographic order (which would put page10 before page2)."""
    parts = re.split(r"(\d+)", path.name)
    return tuple(int(p) if p.isdigit() else p for p in parts)


class BatchProcessor:
    def __init__(self, processor: ChechenOcrProcessor):
        self.processor = processor

    def _read_raw_text(self, path: Path) -> str:
        suffix = path.suffix.lower()

        if suffix in _TEXT_EXTENSIONS:
            return path.read_text(encoding="utf-8", errors="replace")

        if suffix in _DOCX_EXTENSIONS:
            from .io.docx_reader import extract_docx_to_text

            return extract_docx_to_text(path, settings=self.processor.settings)

        if suffix in _PDF_EXTENSIONS:
            if self.processor.ocr_engine is None:
                raise ValueError(f"No OcrEngine configured; cannot process PDF {path}")
            from .io.pdf_reader import process_pdf_pages

            return process_pdf_pages(
                path,
                ocr_engine=self.processor.ocr_engine,
                lang=self.processor.settings.default_lang,
                settings=self.processor.settings,
            )

        if suffix in _IMAGE_EXTENSIONS:
            if self.processor.ocr_engine is None:
                raise ValueError(f"No OcrEngine configured; cannot process image {path}")
            result = self.processor.ocr_engine.recognize(
                path, lang=self.processor.settings.default_lang
            )
            return result.text

        raise ValueError(
            f"Unsupported file extension '{suffix}' for {path.name}. "
            f"Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )

    def process_directory(
        self,
        input_dir: Path,
        pattern: str = "*",
        stop_on_error: bool = False,
        ocr_engine_name: str | None = None,
    ) -> BatchResult:
        input_dir = Path(input_dir)
        paths = sorted(
            (p for p in input_dir.glob(pattern) if p.suffix.lower() in SUPPORTED_EXTENSIONS),
            key=_natural_sort_key,
        )

        if not paths:
            raise ValueError(
                f"No supported files found in {input_dir} matching '{pattern}' "
                f"(supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))})"
            )

        logger.info("batch: found %d file(s) in %s", len(paths), input_dir)

        sections: list[str] = []
        skipped: list[tuple[str, str]] = []

        for i, path in enumerate(paths, start=1):
            logger.debug("batch: reading %d/%d: %s", i, len(paths), path.name)
            try:
                raw_text = self._read_raw_text(path)
            except Exception as exc:
                logger.error("batch: skipping %s (%s)", path.name, exc)
                skipped.append((path.name, str(exc)))
                if stop_on_error:
                    raise
                continue

            header = f"===== Страница {i} | {path.name} ====="
            sections.append(f"{header}\n\n{raw_text}\n")

        if not sections:
            raise ValueError(f"All {len(paths)} file(s) in {input_dir} failed to read; see logs")

        combined_raw_text = "\n".join(sections)
        doc = self.processor.process_text(combined_raw_text, ocr_engine_name=ocr_engine_name)
        metrics = self.processor.compute_metrics(doc)

        per_file = self._build_per_file_breakdown(doc)

        logger.info(
            "batch: processed %d file(s) (%d skipped): %d words, %d corrections, %d suspicious",
            len(paths) - len(skipped),
            len(skipped),
            metrics.total_words,
            metrics.total_corrections,
            metrics.suspicious_count,
        )

        return BatchResult(doc=doc, metrics=metrics, per_file=per_file, skipped_files=skipped)

    def _build_per_file_breakdown(self, doc: ProcessedDocument) -> list[BatchFileResult]:
        spans = build_page_index(doc.corrected_text)
        if not spans:
            return []

        word_re = re.compile(r"\S+")
        suspicious_words = {sw.word for sw in doc.suspicious}

        results: list[BatchFileResult] = []
        for span in spans:
            span_text = doc.corrected_text[span.start : span.end]
            # The span, as parsed by build_page_index, starts at the
            # "===== Страница N | filename =====" marker line itself --
            # strip it before counting, or its own tokens ("=====",
            # "Страница", the number, "|", the filename) would be
            # counted as if they were part of this file's content.
            _, _, span_body = span_text.partition("\n")
            words = word_re.findall(span_body)

            # Correction.position is relative to the single line each
            # corrector ran on (process_text() runs correctors per-line,
            # see processor.py), not to the combined document -- so it
            # can't be compared against span.start/end directly. This
            # substring check is an approximation: it counts a
            # correction as "in this file" if its (before) text occurs
            # anywhere in that file's span, which can double-count a
            # correction if the exact same OCR-damaged text happens to
            # appear on more than one page. Good enough for "which file
            # needs attention," not a precise ledger.
            corrections_in_span = sum(
                1 for c in doc.corrections if c.before and c.before in span_body
            )
            suspicious_in_span = sum(
                1 for w in words if w.strip(".,!?;:()[]{}«»\"'“”„") in suspicious_words
            )

            results.append(
                BatchFileResult(
                    index=int(span.page) if span.page.isdigit() else -1,
                    filename=span.image_file,
                    word_count=len(words),
                    correction_count=corrections_in_span,
                    suspicious_count=suspicious_in_span,
                )
            )

        return results

    def export(
        self,
        result: BatchResult,
        output_dir: Path,
        base_name: str = "book",
        write_docx: bool = False,
    ) -> dict[str, Path]:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        paths = {
            "corrected_txt": output_dir / f"{base_name}.txt",
            "corrections_report": output_dir / f"{base_name}_corrections.txt",
            "review_csv": output_dir / f"{base_name}_review.csv",
            "per_file_report": output_dir / f"{base_name}_per_file_report.csv",
        }

        paths["corrected_txt"].write_text(result.doc.corrected_text, encoding="utf-8")
        self.processor.export_corrections_report(result.doc, paths["corrections_report"])
        self.processor.export_review_table_csv(result.doc, paths["review_csv"])
        self._export_per_file_report(result, paths["per_file_report"])

        if write_docx:
            paths["docx"] = output_dir / f"{base_name}.docx"
            self.processor.export_docx(result.doc, paths["docx"])

        return paths

    def _export_per_file_report(self, result: BatchResult, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "index",
                    "filename",
                    "word_count",
                    "correction_count",
                    "suspicious_count",
                    "suspicious_ratio",
                ]
            )
            for r in result.per_file:
                writer.writerow(
                    [
                        r.index,
                        r.filename,
                        r.word_count,
                        r.correction_count,
                        r.suspicious_count,
                        f"{r.suspicious_ratio:.4f}",
                    ]
                )
            if result.skipped_files:
                writer.writerow([])
                writer.writerow(["skipped_file", "reason"])
                for filename, reason in result.skipped_files:
                    writer.writerow([filename, reason])
