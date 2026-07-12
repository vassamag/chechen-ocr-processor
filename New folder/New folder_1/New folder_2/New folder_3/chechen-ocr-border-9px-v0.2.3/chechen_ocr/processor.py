"""
processor.py

The single public entry point for the package: ChechenOcrProcessor.

Separates two independent concerns that were mixed together in the
original process.py:

  1. OcrEngine  -- turns an image into raw text (Tesseract, Vision API, ...)
  2. Pipeline   -- turns raw text into corrected text + a change log

build_pipeline() picks which Correctors to run based on which OCR
engine produced the text, since some correctors specifically target
Tesseract-style Latin-lookalike artifacts (see module docstrings on
palochka_pattern.py / common_words.py / vision_api_engine.py).
"""

from __future__ import annotations

import csv
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from .config import Settings
from .core import Correction, Corrector, Pipeline, PipelineContext
from .correctors import (
    CommonWordFixList,
    DirectPalochkaLookalikes,
    GeneralWordFix,
    InternalCapitalizationFix,
    LatinCyrillicHomoglyphFix,
    PatternBasedPalochka,
    PhraseBigramDisambiguator,
    RemainingCharsCleanup,
    SingleCandidateDictionaryFix,
)
from .dictionaries import Dictionaries, load_dictionaries
from .metrics import DocumentMetrics, compute_metrics
from .ocr.base import OcrEngine
from .review import ApplyResult, ReviewRow, apply_review_rows, build_review_rows
from .review.schema import REVIEW_CSV_FIELDNAMES
from .suspicious import SuspiciousWord, detect_suspicious_words

logger = logging.getLogger(__name__)

# Lines that must never be touched by correction or suspicious-word
# detection (page markers, service headers from the original scanning
# batch process). Ported from process_text.py::is_protected_service_line.
_PROTECTED_LINE_PREFIXES = (
    "Распознанный текст из JPG-файлов",
    "Страницы отсортированы",
    "OCR автоматический",
)


def is_protected_service_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if stripped.startswith(_PROTECTED_LINE_PREFIXES):
        return True
    return stripped.startswith("=====") and "Страница" in stripped


def _index_to_letters(index: int) -> str:
    letters = []
    index += 1
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        letters.append(chr(ord("a") + remainder))
    return "".join(reversed(letters))


_NUMBER_RE = re.compile(r"(?<![\wӀ])\d+(?![\wӀ])", flags=re.UNICODE)


def _protect_numeric_tokens(text: str) -> tuple[str, dict[str, str]]:
    """
    Replaces standalone numeric tokens with digit-free placeholders so
    that palochka correctors (which treat '1' as a palochka lookalike)
    cannot touch page numbers, verse numbers, etc.
    """
    replacements: dict[str, str] = {}
    counter = 0

    def repl(match: re.Match[str]) -> str:
        nonlocal counter
        key = f"\u00a4num{_index_to_letters(counter)}\u00a4"
        counter += 1
        replacements[key] = match.group(0)
        return key

    return _NUMBER_RE.sub(repl, text), replacements


def _restore_numeric_tokens(text: str, replacements: dict[str, str]) -> str:
    for key, original in replacements.items():
        text = text.replace(key, original)
    return text


def build_pipeline(ocr_engine_name: str | None) -> Pipeline:
    """
    Default pipeline. Tesseract-specific lookalike correctors are
    skipped for engines that don't produce that kind of artifact
    (currently: anything other than "tesseract"). The general-purpose
    steps (dictionary disambiguation, phrase-context tiebreak, non-
    palochka letter-confusion fix) are engine-independent and always
    run.

    NOTE: WordSegmentationFix (correctors/word_segmentation.py) is
    intentionally NOT included here. Golden-file testing
    (tests/golden/golden_diff.py) found it net harmful on real data:
    Chechen's agglutinative morphology means a real word simply
    missing from chechen_words.txt can coincidentally have a valid
    decomposition into two OTHER, unrelated dictionary words, and this
    happens often enough in practice to outweigh the genuine merged-
    word cases it catches (dropped overall similarity from ~92.3% to
    ~83.8% in the initial, unhardened version; still a net regression
    to ~91.0% after hardening thresholds). It remains available for
    explicit opt-in (see WordSegmentationFix's docstring for the full
    finding and tradeoffs) via a custom Pipeline, but is excluded here
    by default.

    NOTE: InternalCapitalizationFix (correctors/internal_capitalization_fix.py)
    is engine-gated the OPPOSITE way from the Tesseract-specific
    correctors above -- it only runs for non-Tesseract engines. Golden-
    file testing found it net harmful specifically for Tesseract
    output (92.41%->92.26%, 77.33%->76.45%): an unexpected mid-word
    capital there is often the first symptom of a still-unresolved
    palochka lookalike that PatternBasedPalochka's pattern only
    matches in lowercase (e.g. "тГ" not "тг"), so fixing the case first
    hides a real error instead of catching it. On Vision-generated
    text this collision is rare (measured at 0.2% on a 590-page real
    book) since that text doesn't have the same lowercase-pattern-
    matching gap, so the fix is enabled there.
    """
    steps: list[Corrector] = []

    if ocr_engine_name in (None, "tesseract"):
        steps += [
            DirectPalochkaLookalikes(),
            PatternBasedPalochka(),
            CommonWordFixList(),
        ]

    steps += [
        LatinCyrillicHomoglyphFix(),
    ]

    if ocr_engine_name not in (None, "tesseract"):
        steps.append(InternalCapitalizationFix())

    steps += [
        SingleCandidateDictionaryFix(),
        PhraseBigramDisambiguator(),
        RemainingCharsCleanup(),
        GeneralWordFix(),
    ]

    return Pipeline(steps)


@dataclass
class ProcessedDocument:
    corrected_text: str
    raw_text: str
    corrections: list[Correction]
    suspicious: list[SuspiciousWord]


class ChechenOcrProcessor:
    """
    Public API.

        processor = ChechenOcrProcessor(
            settings=Settings.default(),
            ocr_engine=TesseractEngine(tesseract_cmd=None),
        )
        result = processor.process_image(Path("page001.jpg"))
        result = processor.process_text(raw_text)
    """

    def __init__(
        self,
        settings: Settings | None = None,
        ocr_engine: OcrEngine | None = None,
        pipeline: Pipeline | None = None,
        dictionaries: Dictionaries | None = None,
    ):
        self.settings = settings or Settings.default()
        self.ocr_engine = ocr_engine
        self._explicit_pipeline = pipeline
        self.dictionaries = dictionaries or load_dictionaries(self.settings.rules_dir)

    def _pipeline_for(self, ocr_engine_name: str | None) -> Pipeline:
        return self._explicit_pipeline or build_pipeline(ocr_engine_name)

    def _ctx(self, ocr_engine_name: str | None) -> PipelineContext:
        return PipelineContext(
            settings=self.settings,
            dictionaries=self.dictionaries,
            ocr_engine_name=ocr_engine_name,
        )

    # -- text mode --------------------------------------------------

    def process_text(self, raw_text: str, ocr_engine_name: str | None = None) -> ProcessedDocument:
        """
        Runs the correction pipeline on raw OCR text, protecting
        numeric tokens and service/page-marker lines the same way the
        original process_text.py did (but as an explicit method
        instead of chunk-splitting-by-side-effect).
        """
        ctx = self._ctx(ocr_engine_name)
        pipeline = self._pipeline_for(ocr_engine_name)

        corrected_lines: list[str] = []
        analysis_lines: list[str] = []
        all_corrections: list[Correction] = []

        for line in raw_text.splitlines(keepends=True):
            body = line.rstrip("\r\n")
            ending = line[len(body) :]

            if is_protected_service_line(body):
                corrected_lines.append(body + ending)
                continue

            protected, replacements = _protect_numeric_tokens(line)
            result = pipeline.run(protected, ctx)
            restored = _restore_numeric_tokens(result.text, replacements)

            corrected_lines.append(restored)
            analysis_lines.append(restored.rstrip("\r\n"))
            all_corrections.extend(result.corrections)

        corrected_text = "".join(corrected_lines)
        suspicious = detect_suspicious_words("\n".join(analysis_lines), ctx)

        doc = ProcessedDocument(
            corrected_text=corrected_text,
            raw_text=raw_text,
            corrections=all_corrections,
            suspicious=suspicious,
        )

        self._log_summary(doc, ocr_engine_name)

        return doc

    def _log_summary(self, doc: ProcessedDocument, ocr_engine_name: str | None) -> None:
        metrics = compute_metrics(doc.corrected_text, doc.corrections, len(doc.suspicious))

        logger.info(
            "processed %d words: %d corrections (%s), %d suspicious (%.1f%%)%s",
            metrics.total_words,
            metrics.total_corrections,
            dict(metrics.corrections_by_rule),
            metrics.suspicious_count,
            metrics.suspicious_ratio * 100,
            f" [engine={ocr_engine_name}]" if ocr_engine_name else "",
        )

        if metrics.suspicious_ratio > self.settings.suspicious_ratio_warning_threshold:
            logger.warning(
                "suspicious-word ratio %.1f%% exceeds threshold %.1f%% "
                "-- this document may be from a low-quality scan; consider "
                "prioritizing it for human review",
                metrics.suspicious_ratio * 100,
                self.settings.suspicious_ratio_warning_threshold * 100,
            )

    # -- image mode ---------------------------------------------------

    def process_image(self, image_path: Path) -> ProcessedDocument:
        if self.ocr_engine is None:
            raise ValueError(
                "No OcrEngine configured. Pass ocr_engine=TesseractEngine(...) "
                "or ocr_engine=OpenAIVisionEngine(...) to ChechenOcrProcessor()."
            )

        logger.debug("running OCR (%s) on %s", self.ocr_engine.name, image_path)
        try:
            ocr_result = self.ocr_engine.recognize(
                Path(image_path), lang=self.settings.default_lang
            )
        except Exception:
            logger.exception("OCR failed (%s) on %s", self.ocr_engine.name, image_path)
            raise
        return self.process_text(ocr_result.text, ocr_engine_name=ocr_result.engine_name)

    def compute_metrics(self, doc: ProcessedDocument) -> DocumentMetrics:
        """Recomputes a DocumentMetrics summary for an already-processed
        document (see metrics.py). Useful for batch jobs that want to
        aggregate/monitor quality across many pages without re-deriving
        this by hand from doc.corrections / doc.suspicious."""
        return compute_metrics(doc.corrected_text, doc.corrections, len(doc.suspicious))

    # -- docx input/output -----------------------------------------------

    def process_docx(self, docx_path: Path) -> ProcessedDocument:
        """
        Extracts plain text from a DOCX (e.g. OCR output that was
        delivered as a DOCX rather than a raw TXT dump) and runs it
        through the same correction pipeline as process_text().
        """
        from .io.docx_reader import extract_docx_to_text

        raw_text = extract_docx_to_text(Path(docx_path), settings=self.settings)
        return self.process_text(raw_text)

    def process_pdf(self, pdf_path: Path, dpi: int = 300) -> ProcessedDocument:
        """
        Treats a PDF as a sequence of scanned page images: rasterizes
        every page and runs each through self.ocr_engine (no attempt
        is made to detect/extract an existing text layer -- see
        io/pdf_reader.py docstring for why that's the right tradeoff
        for this project's actual input: phone-scanned books, where a
        PDF is just an alternate packaging of the same photos, not a
        digitally-authored document).

        Requires an OcrEngine to be configured, and the optional
        'pdf2image' package + system poppler-utils binaries.
        """
        if self.ocr_engine is None:
            raise ValueError(
                "No OcrEngine configured. Pass ocr_engine=TesseractEngine(...) "
                "or ocr_engine=OpenAIVisionEngine(...) to ChechenOcrProcessor()."
            )

        from .io.pdf_reader import process_pdf_pages

        raw_text = process_pdf_pages(
            Path(pdf_path),
            ocr_engine=self.ocr_engine,
            lang=self.settings.default_lang,
            dpi=dpi,
            settings=self.settings,
        )
        return self.process_text(raw_text, ocr_engine_name=self.ocr_engine.name)

    def export_docx(
        self,
        doc: ProcessedDocument,
        path: Path,
        highlight_suspicious: bool = True,
    ) -> None:
        """Writes the corrected text to a DOCX, optionally highlighting
        suspicious words in yellow for visual review."""
        from .io.docx_writer import save_docx

        suspicious_words = [sw.word for sw in doc.suspicious] if highlight_suspicious else None
        save_docx(doc.corrected_text, Path(path), suspicious_words=suspicious_words)

    # -- human review workflow -------------------------------------------

    def build_review_rows(self, doc: ProcessedDocument) -> list[ReviewRow]:
        """Builds one ReviewRow per suspicious word, with raw + corrected
        context, ready for a human to fill in `decision`/`replacement`."""
        return build_review_rows(doc.raw_text, doc.corrected_text, doc.suspicious)

    def export_review_table_csv(self, doc: ProcessedDocument, path: Path) -> None:
        """Writes the full context-rich review table (see
        review.schema.REVIEW_CSV_FIELDNAMES) for a human reviewer."""
        rows = self.build_review_rows(doc)
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=REVIEW_CSV_FIELDNAMES)
            writer.writeheader()
            for row in rows:
                writer.writerow(row.as_csv_dict())

    def apply_review_table_csv(
        self,
        doc: ProcessedDocument,
        review_csv_path: Path,
        allow_word_fallback: bool = False,
    ) -> tuple[str, list[ApplyResult]]:
        """
        Reads a human-edited review CSV (decision/replacement columns
        filled in) and applies "replace" rows to doc.corrected_text.
        Returns (new_text, results) -- results is a full per-row audit
        trail (see review.apply_review_table.ApplyResult), including
        rows that were skipped or not considered.
        """
        with Path(review_csv_path).open("r", encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        return apply_review_rows(doc.corrected_text, rows, allow_word_fallback=allow_word_fallback)

    # -- reporting ------------------------------------------------------

    def export_suspicious_csv(self, doc: ProcessedDocument, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["word", "reason", "candidates", "decision", "replacement"])
            for sw in doc.suspicious:
                writer.writerow([sw.word, sw.reason, ", ".join(sw.candidates), "", ""])

    def export_corrections_report(self, doc: ProcessedDocument, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [f"{c.rule}: {c.before} -> {c.after}" for c in doc.corrections]
        path.write_text("\n".join(lines) + "\n" if lines else "No corrections.\n", encoding="utf-8")
