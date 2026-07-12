"""
cli.py

Thin CLI wrappers over ChechenOcrProcessor, replacing the old
standalone scripts (process.py, process_text.py). Old script names
can be kept as one-line shims during migration, e.g.:

    # process_text.py (deprecated shim)
    from chechen_ocr.cli import main_text
    if __name__ == "__main__":
        main_text()
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import TYPE_CHECKING

from .config import Settings
from .processor import ChechenOcrProcessor

if TYPE_CHECKING:
    from .processor import ProcessedDocument


def _common_paths(output: Path) -> dict[str, Path]:
    return {
        "corrected_txt": output.with_suffix(".txt"),
        "corrections_report": output.with_name(output.stem + "_corrections.txt"),
        "suspicious_csv": output.with_name(output.stem + "_suspicious.csv"),
        "review_csv": output.with_name(output.stem + "_review.csv"),
        "docx": output.with_suffix(".docx"),
    }


def _write_common_outputs(
    processor: ChechenOcrProcessor,
    doc: ProcessedDocument,
    output: Path,
    write_docx: bool,
) -> None:
    paths = _common_paths(output)
    paths["corrected_txt"].parent.mkdir(parents=True, exist_ok=True)
    paths["corrected_txt"].write_text(doc.corrected_text, encoding="utf-8")
    processor.export_corrections_report(doc, paths["corrections_report"])
    processor.export_suspicious_csv(doc, paths["suspicious_csv"])
    processor.export_review_table_csv(doc, paths["review_csv"])

    if write_docx:
        processor.export_docx(doc, paths["docx"])

    print(f"Corrected TXT: {paths['corrected_txt']}")
    print(f"Review CSV (context for human review): {paths['review_csv']}")
    if write_docx:
        print(f"Corrected DOCX (suspicious words highlighted): {paths['docx']}")
    print(f"Corrections: {len(doc.corrections)}")
    print(f"Suspicious words: {len(doc.suspicious)}")


def main_text() -> None:
    parser = argparse.ArgumentParser(description="Chechen OCR text post-correction")
    parser.add_argument("input", help="Input raw OCR TXT or DOCX path")
    parser.add_argument("--output", default="output/result", help="Output base path (no extension)")
    parser.add_argument("--rules-dir", default=None, help="Path to rules/ directory")
    parser.add_argument("--docx-output", action="store_true", help="Also write a highlighted DOCX")
    args = parser.parse_args()

    settings = Settings.default()
    if args.rules_dir:
        settings = Settings(rules_dir=Path(args.rules_dir), output_dir=settings.output_dir)

    processor = ChechenOcrProcessor(settings=settings)

    input_path = Path(args.input)
    if input_path.suffix.lower() == ".docx":
        doc = processor.process_docx(input_path)
    else:
        raw_text = input_path.read_text(encoding="utf-8", errors="replace")
        doc = processor.process_text(raw_text)

    _write_common_outputs(processor, doc, Path(args.output), write_docx=args.docx_output)


def main_image() -> None:
    parser = argparse.ArgumentParser(description="Chechen OCR image/PDF post-correction")
    parser.add_argument("input", help="Input image or PDF path")
    parser.add_argument("--output", default="output/result", help="Output base path (no extension)")
    parser.add_argument("--rules-dir", default=None, help="Path to rules/ directory")
    parser.add_argument("--tesseract-cmd", default=None, help="Path to tesseract binary")
    parser.add_argument("--lang", default="rus")
    parser.add_argument("--pdf-dpi", type=int, default=300, help="Rasterization DPI for PDF input")
    parser.add_argument("--docx-output", action="store_true", help="Also write a highlighted DOCX")
    args = parser.parse_args()

    from .ocr.tesseract_engine import TesseractEngine

    settings = Settings(
        rules_dir=Path(args.rules_dir) if args.rules_dir else Settings.default().rules_dir,
        tesseract_cmd=args.tesseract_cmd,
        default_lang=args.lang,
    )
    processor = ChechenOcrProcessor(
        settings=settings,
        ocr_engine=TesseractEngine(tesseract_cmd=settings.tesseract_cmd),
    )

    input_path = Path(args.input)
    if input_path.suffix.lower() == ".pdf":
        doc = processor.process_pdf(input_path, dpi=args.pdf_dpi)
    else:
        doc = processor.process_image(input_path)

    _write_common_outputs(processor, doc, Path(args.output), write_docx=args.docx_output)


def main_apply_review() -> None:
    """
    Applies a human-reviewed CSV (decision/replacement columns filled
    in) back onto a previously corrected text, producing a final,
    human-approved output.
    """
    parser = argparse.ArgumentParser(
        description="Apply a reviewed CSV's decisions onto corrected Chechen OCR text"
    )
    parser.add_argument("corrected_txt", help="Path to the corrected TXT to apply changes to")
    parser.add_argument("review_csv", help="Path to the human-reviewed CSV")
    parser.add_argument("--output", required=True, help="Path for the final, reviewed TXT")
    parser.add_argument(
        "--allow-word-fallback",
        action="store_true",
        help="If context-based replacement fails, fall back to a unique whole-word "
        "replacement when the word appears exactly once in the whole text",
    )
    args = parser.parse_args()

    from .processor import ProcessedDocument

    corrected_text = Path(args.corrected_txt).read_text(encoding="utf-8", errors="replace")
    # apply_review_table_csv only needs .corrected_text from the
    # ProcessedDocument -- raw_text/corrections/suspicious aren't used
    # by the apply step, so a minimal stand-in is enough here.
    doc = ProcessedDocument(
        corrected_text=corrected_text, raw_text="", corrections=[], suspicious=[]
    )

    processor = ChechenOcrProcessor(settings=Settings.default())
    new_text, results = processor.apply_review_table_csv(
        doc, Path(args.review_csv), allow_word_fallback=args.allow_word_fallback
    )

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(new_text, encoding="utf-8")

    status_counts: dict[str, int] = {}
    for r in results:
        status_counts[r.status] = status_counts.get(r.status, 0) + 1

    print(f"Final reviewed TXT: {output_path}")
    print(f"Status counts: {status_counts}")


def main_batch() -> None:
    """
    Processes an entire directory of scanned pages (images, PDFs,
    TXT, DOCX -- any mix) as one connected book, producing a single
    combined corrected TXT, review CSV, corrections report, and a
    per-file quality breakdown (see BatchProcessor.worst_files) to
    prioritize which pages need human review first.
    """
    parser = argparse.ArgumentParser(
        description="Batch-process a whole directory of scanned pages as one book"
    )
    parser.add_argument("input_dir", help="Directory containing scanned pages")
    parser.add_argument("--output-dir", required=True, help="Directory for output files")
    parser.add_argument("--base-name", default="book", help="Base name for output files")
    parser.add_argument("--pattern", default="*", help="Glob pattern for input files")
    parser.add_argument("--rules-dir", default=None, help="Path to rules/ directory")
    parser.add_argument("--tesseract-cmd", default=None, help="Path to tesseract binary")
    parser.add_argument("--lang", default="rus")
    parser.add_argument("--docx-output", action="store_true", help="Also write a highlighted DOCX")
    parser.add_argument(
        "--stop-on-error",
        action="store_true",
        help="Abort on the first unreadable file instead of skipping it",
    )
    args = parser.parse_args()

    from .batch import BatchProcessor
    from .ocr.tesseract_engine import TesseractEngine

    settings = Settings(
        rules_dir=Path(args.rules_dir) if args.rules_dir else Settings.default().rules_dir,
        tesseract_cmd=args.tesseract_cmd,
        default_lang=args.lang,
    )
    processor = ChechenOcrProcessor(
        settings=settings,
        ocr_engine=TesseractEngine(tesseract_cmd=settings.tesseract_cmd),
    )
    batch = BatchProcessor(processor)

    result = batch.process_directory(
        Path(args.input_dir), pattern=args.pattern, stop_on_error=args.stop_on_error
    )
    output_paths = batch.export(
        result, Path(args.output_dir), base_name=args.base_name, write_docx=args.docx_output
    )

    print(f"Processed {len(result.per_file)} file(s), {len(result.skipped_files)} skipped")
    print(
        f"Words: {result.metrics.total_words}, corrections: {result.metrics.total_corrections}, "
        f"suspicious: {result.metrics.suspicious_count}"
    )
    print("Outputs:")
    for name, path in output_paths.items():
        print(f"  {name}: {path}")

    worst = result.worst_files[:5]
    if worst:
        print("\nFiles most worth prioritizing for review (highest suspicious ratio):")
        for f in worst:
            print(
                f"  {f.filename}: {f.suspicious_ratio:.1%} ({f.suspicious_count}/{f.word_count} words)"
            )


if __name__ == "__main__":
    main_text()
