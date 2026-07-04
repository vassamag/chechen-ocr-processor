import argparse
import importlib.util
import re
from pathlib import Path


VERSION = "v5.3.3"


def load_process_module():
    """
    Loads the existing process.py as a module.

    We reuse the stable post-correction logic from process.py,
    but this wrapper protects TXT-specific metadata and numeric tokens.
    """
    process_path = Path("process.py")

    if not process_path.exists():
        raise FileNotFoundError("process.py not found in current directory")

    spec = importlib.util.spec_from_file_location("chechen_process", process_path)
    module = importlib.util.module_from_spec(spec)

    if spec.loader is None:
        raise RuntimeError("Could not load process.py")

    spec.loader.exec_module(module)

    # Load palochka dictionary for text mode too.
    if hasattr(module, "load_palochka_words"):
        module.PALOCHKA_DICTIONARY = module.load_palochka_words()

    return module


def index_to_letters(index: int) -> str:
    """
    Converts 0 -> a, 1 -> b, ..., 25 -> z, 26 -> aa, etc.
    Used to create placeholders without digits.
    """
    letters = []
    index += 1

    while index > 0:
        index, remainder = divmod(index - 1, 26)
        letters.append(chr(ord("a") + remainder))

    return "".join(reversed(letters))


def is_protected_service_line(line: str) -> bool:
    """
    Lines that must not be post-corrected or suspicious-analyzed.
    """
    stripped = line.strip()

    if not stripped:
        return False

    if stripped.startswith("Распознанный текст из JPG-файлов"):
        return True

    if stripped.startswith("Страницы отсортированы"):
        return True

    if stripped.startswith("OCR автоматический"):
        return True

    if stripped.startswith("=====") and "Страница" in stripped:
        return True

    return False


def protect_numeric_tokens(text: str):
    """
    Protects standalone numeric tokens before running Chechen post-correction.

    Example:
    11 -> ¤numaa¤
    273 -> ¤numab¤

    The placeholders contain no digits, so process.py cannot convert 1 -> Ӏ.
    """
    replacements = {}

    pattern = re.compile(r"(?<![\wӀ])\d+(?![\wӀ])", flags=re.UNICODE)

    counter = 0

    def repl(match):
        nonlocal counter

        original = match.group(0)
        key = f"¤num{index_to_letters(counter)}¤"
        counter += 1

        replacements[key] = original
        return key

    protected_text = pattern.sub(repl, text)
    return protected_text, replacements


def restore_numeric_tokens(text: str, replacements: dict) -> str:
    """
    Restores numeric placeholders back to original numbers.
    """
    for key, original in replacements.items():
        text = text.replace(key, original)
    return text


def post_correct_chunk_safely(chunk: str, processor) -> str:
    """
    Protects numeric tokens, runs post-correction once per text chunk,
    then restores numeric tokens.
    """
    if not chunk.strip():
        return chunk

    protected_chunk, numeric_replacements = protect_numeric_tokens(chunk)
    corrected_chunk = processor.post_correct_chechen_ocr(protected_chunk)
    corrected_chunk = restore_numeric_tokens(corrected_chunk, numeric_replacements)

    return corrected_chunk


def post_correct_text_safely(raw_text: str, processor) -> str:
    """
    Processes text in chunks.

    Service/page-marker lines are preserved exactly.
    Normal text between service lines is processed as chunks.

    This avoids the v5.3.2 problem where line-by-line processing
    inserted excessive blank lines.
    """
    output_parts = []
    current_chunk = []

    lines = raw_text.splitlines(keepends=True)

    for line in lines:
        body = line.rstrip("\r\n")
        ending = line[len(body):]

        if is_protected_service_line(body):
            if current_chunk:
                chunk_text = "".join(current_chunk)
                output_parts.append(post_correct_chunk_safely(chunk_text, processor))
                current_chunk = []

            output_parts.append(body + ending)
        else:
            current_chunk.append(line)

    if current_chunk:
        chunk_text = "".join(current_chunk)
        output_parts.append(post_correct_chunk_safely(chunk_text, processor))

    return "".join(output_parts)


def build_suspicious_analysis_text(corrected_text: str) -> str:
    """
    Removes service/page-marker lines before suspicious-word detection.

    This prevents entries like:
    IMG-20250825-WA0022
    JPG-файлов
    Страница
    from polluting suspicious reports.
    """
    lines_for_analysis = []

    for line in corrected_text.splitlines():
        if is_protected_service_line(line):
            continue

        lines_for_analysis.append(line)

    return "\n".join(lines_for_analysis)


def process_text_file(input_path: Path, output_base: Path) -> None:
    processor = load_process_module()

    processor.CORRECTION_LOG.clear()
    processor.SUSPICIOUS_LOG.clear()

    input_path = Path(input_path)
    output_base = Path(output_base)

    if not input_path.exists():
        raise FileNotFoundError(f"Input text file not found: {input_path}")

    output_base.parent.mkdir(parents=True, exist_ok=True)

    raw_text = input_path.read_text(encoding="utf-8", errors="replace")
    corrected_text = post_correct_text_safely(raw_text, processor)

    suspicious_analysis_text = build_suspicious_analysis_text(corrected_text)
    suspicious_words = processor.detect_suspicious_words(suspicious_analysis_text)

    raw_txt_path = output_base.with_name(output_base.stem + "_raw_ocr.txt")
    corrected_txt_path = output_base.with_suffix(".txt")
    correction_report_path = output_base.with_name(output_base.stem + "_corrections.txt")
    suspicious_report_path = output_base.with_name(output_base.stem + "_suspicious.txt")

    processor.save_txt(raw_text, raw_txt_path)
    processor.save_txt(corrected_text, corrected_txt_path)
    processor.save_correction_report(correction_report_path)
    processor.save_suspicious_report(suspicious_report_path)

    print(f"process_text.py version: {VERSION}")
    print(f"Input TXT: {input_path}")
    print(f"Raw OCR copy saved: {raw_txt_path}")
    print(f"Corrected TXT saved: {corrected_txt_path}")
    print(f"Correction report saved: {correction_report_path}")
    print(f"Suspicious report saved: {suspicious_report_path}")
    print(f"Automatic corrections logged: {len(processor.CORRECTION_LOG)}")
    print(f"Suspicious words detected: {len(suspicious_words)}")


def main():
    parser = argparse.ArgumentParser(
        description="Run Chechen OCR post-correction on an existing OCR TXT file"
    )
    parser.add_argument("input", help="Input raw OCR TXT path")
    parser.add_argument(
        "--output",
        default="output/text_result.txt",
        help="Output base path. Extension is used for corrected TXT name.",
    )

    args = parser.parse_args()

    process_text_file(Path(args.input), Path(args.output))


if __name__ == "__main__":
    main()