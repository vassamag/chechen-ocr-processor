# make_review_table_with_context.py
# v1.0
#
# Builds suspicious_review_table_with_context.csv for manual Chechen OCR review.
#
# Main principle:
#   suspicious entries are NOT auto-fixed here.
#   The script only gives raw/corrected context for human decision.
#
# Output columns:
#   id, page, image_file, word, reason, candidates,
#   corrected_context, raw_context, decision, replacement, notes
#
# Usage on your Windows machine:
#   cd C:\Users\vassa_000\Desktop\TesserAct
#   python make_review_table_with_context.py
#
# Optional:
#   python make_review_table_with_context.py --context 180

from pathlib import Path
import argparse
import csv
import re
from typing import Dict, List, Tuple, Optional


DEFAULT_BASE_DIR = Path(r"C:\Users\vassa_000\Desktop\TesserAct")

DEFAULT_RAW_NAMES = [
    "recognized_text_ordered.txt",
    "recognized_text_ordered_v5_3_5_raw_ocr.txt",
]

DEFAULT_FIXED_NAMES = [
    "recognized_text_ordered_chechen_fixed.txt",
    "recognized_text_ordered_v5_3_5_fixed.txt",
]

DEFAULT_CORRECTIONS_NAMES = [
    "recognized_text_ordered_v5_3_5_corrections.txt",
    "corrections_report.txt",
    "chechen_ocr_corrections_report.txt",
]

DEFAULT_SUSPICIOUS_NAMES = [
    "recognized_text_ordered_v5_3_5_suspicious.txt",
    "suspicious_report.txt",
]


PAGE_RE = re.compile(
    r"^===== Страница\s+(?P<page>\d+)\s+\|\s+(?P<image>[^=]+?)\s+=====$",
    re.MULTILINE,
)


def read_text(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path}")
    return path.read_text(encoding="utf-8", errors="replace")


def first_existing(base_dir: Path, names: List[str]) -> Optional[Path]:
    for name in names:
        p = base_dir / name
        if p.exists():
            return p
    return None


def normalize_space(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def parse_suspicious_line(line: str) -> Optional[Dict[str, str]]:
    """
    Expected format:
      word | reason: ... | candidates: ...

    Important:
      The suspicious word itself may contain "|" as an OCR artifact.
      Therefore do NOT split blindly on "|".
    """
    line = line.strip()
    if not line:
        return None

    m = re.match(r"^(?P<word>.*?)\s+\|\s+reason:\s*(?P<reason>.*?)\s+\|\s+candidates:\s*(?P<candidates>.*)$", line)
    if m:
        word = m.group("word").strip()
        reason = m.group("reason").strip()
        candidates = m.group("candidates").strip()
    else:
        # Conservative fallback.
        word = line.strip()
        reason = ""
        candidates = ""

    if not word:
        return None

    return {
        "word": word,
        "reason": reason,
        "candidates": candidates,
    }


def parse_suspicious_report(text: str) -> List[Dict[str, str]]:
    rows = []
    for line in text.splitlines():
        item = parse_suspicious_line(line)
        if item:
            rows.append(item)
    return rows


def apply_corrections_once_per_log(raw_text: str, corrections_text: str) -> Tuple[str, int, int]:
    """
    Reconstructs an approximate corrected text from raw OCR + corrections log.

    Important:
      Each line in corrections log represents one correction occurrence.
      Therefore we replace only one occurrence per log line.

    Accepted log examples:
      palochka_direct: І -> Ӏ
      palochka_pattern: тј -> тӀ
      dictionary: хГумма -> хӀумма
    """
    text = raw_text
    applied = 0
    missed = 0

    line_re = re.compile(r"^[^:]+:\s*(.*?)\s*->\s*(.*?)\s*$")

    for line in corrections_text.splitlines():
        line = line.strip()
        if not line:
            continue

        m = line_re.match(line)
        if not m:
            continue

        old, new = m.group(1), m.group(2)

        if not old:
            continue

        if old in text:
            text = text.replace(old, new, 1)
            applied += 1
        else:
            missed += 1

    return text, applied, missed


def build_page_index(text: str) -> List[Dict[str, object]]:
    """
    Builds page spans from headers:
      ===== Страница 11 | IMG-...jpg =====
    """
    matches = list(PAGE_RE.finditer(text))
    pages = []

    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        pages.append({
            "page": m.group("page"),
            "image_file": m.group("image").strip(),
            "start": start,
            "end": end,
        })

    return pages


def meta_for_position(pages: List[Dict[str, object]], pos: int) -> Tuple[str, str]:
    if pos < 0:
        return "", ""

    # Linear scan is OK for a few hundred pages.
    for p in pages:
        if int(p["start"]) <= pos < int(p["end"]):
            return str(p["page"]), str(p["image_file"])

    return "", ""


def context_around(text: str, word: str, start_pos: int, context_chars: int) -> Tuple[str, int]:
    """
    Finds word occurrence near sequential start_pos.
    Falls back to full-text search if sequential search fails.
    """
    if not word:
        return "", -1

    # Prefer exact plain search. OCR tokens often contain punctuation-like chars,
    # so word-boundary regex can miss real entries.
    pos = text.find(word, max(0, start_pos))
    if pos == -1:
        pos = text.find(word)

    if pos == -1:
        return "", -1

    a = max(0, pos - context_chars)
    b = min(len(text), pos + len(word) + context_chars)

    ctx = text[a:b]
    rel = pos - a
    ctx = ctx[:rel] + "[[" + ctx[rel:rel + len(word)] + "]]" + ctx[rel + len(word):]

    return normalize_space(ctx), pos



def context_at_position(text: str, pos: int, context_chars: int) -> Tuple[str, str]:
    """
    Builds context around a known approximate position and highlights the token
    currently occupying that position.

    Used when suspicious word exists in raw OCR, but the corrected text already
    changed that exact token.
    """
    if pos < 0 or pos >= len(text):
        return "", ""

    left = pos
    while left > 0 and not text[left - 1].isspace():
        left -= 1

    right = pos
    while right < len(text) and not text[right].isspace():
        right += 1

    token = text[left:right]

    a = max(0, left - context_chars)
    b = min(len(text), right + context_chars)

    ctx = text[a:left] + "[[" + text[left:right] + "]]" + text[right:b]
    return normalize_space(ctx), token


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-dir", default=str(DEFAULT_BASE_DIR))
    parser.add_argument("--raw", default="")
    parser.add_argument("--fixed", default="")
    parser.add_argument("--corrections", default="")
    parser.add_argument("--suspicious", default="")
    parser.add_argument("--out", default="suspicious_review_table_with_context.csv")
    parser.add_argument("--context", type=int, default=160)
    args = parser.parse_args()

    base_dir = Path(args.base_dir)

    raw_path = Path(args.raw) if args.raw else first_existing(base_dir, DEFAULT_RAW_NAMES)
    fixed_path = Path(args.fixed) if args.fixed else first_existing(base_dir, DEFAULT_FIXED_NAMES)
    corrections_path = Path(args.corrections) if args.corrections else first_existing(base_dir, DEFAULT_CORRECTIONS_NAMES)
    suspicious_path = Path(args.suspicious) if args.suspicious else first_existing(base_dir, DEFAULT_SUSPICIOUS_NAMES)

    if raw_path is None:
        raise FileNotFoundError("Raw OCR text file not found.")
    if suspicious_path is None:
        raise FileNotFoundError("Suspicious report file not found.")

    raw_text = read_text(raw_path)
    suspicious_text = read_text(suspicious_path)

    derived_note = ""
    if fixed_path is not None and fixed_path.exists():
        corrected_text = read_text(fixed_path)
        corrected_source = str(fixed_path)
    elif corrections_path is not None and corrections_path.exists():
        corrections_text = read_text(corrections_path)
        corrected_text, applied, missed = apply_corrections_once_per_log(raw_text, corrections_text)
        corrected_source = f"derived from raw + corrections log ({applied} applied, {missed} missed)"
        derived_note = (
            f"corrected_context derived from raw OCR + corrections log; "
            f"applied={applied}; missed={missed}"
        )
    else:
        corrected_text = raw_text
        corrected_source = "raw OCR only; no fixed text or corrections log found"
        derived_note = "corrected_context equals raw_context; no fixed text or corrections log found"

    suspicious_rows = parse_suspicious_report(suspicious_text)

    raw_pages = build_page_index(raw_text)
    corrected_pages = build_page_index(corrected_text)

    out_rows = []
    raw_search_pos = 0
    corrected_search_pos = 0

    for idx, item in enumerate(suspicious_rows, start=1):
        word = item["word"]

        raw_ctx, raw_pos = context_around(
            raw_text, word, raw_search_pos, args.context
        )
        corrected_ctx, corrected_pos = context_around(
            corrected_text, word, corrected_search_pos, args.context
        )

        corrected_token_at_raw_pos = ""

        # If the suspicious raw token was already changed in corrected text,
        # use the raw position as a safe approximate anchor and highlight
        # whatever token now occupies that same place in corrected text.
        if corrected_pos == -1 and raw_pos != -1:
            corrected_ctx, corrected_token_at_raw_pos = context_at_position(
                corrected_text, raw_pos, args.context
            )
            corrected_pos = raw_pos

        if corrected_pos != -1:
            corrected_search_pos = corrected_pos + len(word)
        if raw_pos != -1:
            raw_search_pos = raw_pos + len(word)

        page, image_file = "", ""

        if corrected_pos != -1:
            page, image_file = meta_for_position(corrected_pages, corrected_pos)

        if not page and raw_pos != -1:
            page, image_file = meta_for_position(raw_pages, raw_pos)

        notes = derived_note if derived_note else ""

        if corrected_token_at_raw_pos and corrected_token_at_raw_pos != word:
            notes = (
                (notes + "; " if notes else "")
                + f"corrected token at raw position: {corrected_token_at_raw_pos}"
            )

        if not corrected_ctx and not raw_ctx:
            notes = (notes + "; " if notes else "") + "context not found; нужен оригинал страницы"

        out_rows.append({
            "id": idx,
            "page": page,
            "image_file": image_file,
            "word": word,
            "reason": item["reason"],
            "candidates": item["candidates"],
            "corrected_context": corrected_ctx,
            "raw_context": raw_ctx,
            "decision": "pending",
            "replacement": "",
            "notes": notes,
        })

    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = base_dir / out_path

    with out_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "id",
                "page",
                "image_file",
                "word",
                "reason",
                "candidates",
                "corrected_context",
                "raw_context",
                "decision",
                "replacement",
                "notes",
            ],
        )
        writer.writeheader()
        writer.writerows(out_rows)

    print(f"Raw OCR: {raw_path}")
    print(f"Suspicious report: {suspicious_path}")
    print(f"Corrected source: {corrected_source}")
    print(f"Created: {out_path}")
    print(f"Rows: {len(out_rows)}")


if __name__ == "__main__":
    main()
