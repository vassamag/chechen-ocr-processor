#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
prefill_review_from_manual_docx.py v1.1

Uses a manually cleaned DOCX as a reference to prefill suspicious_review_table*.csv.
It creates a NEW CSV only; it does not modify the OCR text.

Typical local run from C:\Users\vassa_000\Desktop\TesserAct:
  python prefill_review_from_manual_docx.py ^
    --review output\suspicious_review_table_with_context.csv ^
    --manual-docx "output\recognized_text_after_70_pages (1).docx" ^
    --out output\suspicious_review_table_prefilled_from_manual_docx.csv ^
    --report output\manual_docx_prefill_report.txt
"""
from __future__ import annotations

import argparse
import csv
import re
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    from docx import Document
except ImportError:
    Document = None

VERSION = "1.1"
PALOCHKA = "Ӏ"  # U+04C0 CYRILLIC LETTER PALOCHKA

WORD_RE = re.compile(r"[0-9A-Za-zА-Яа-яЁёІіЇїӀӏ\[\]\|!]+(?:[-’'][0-9A-Za-zА-Яа-яЁёІіЇїӀӏ\[\]\|!]+)*", re.UNICODE)
BRACKET_RE = re.compile(r"\[\[(.*?)\]\]")

OCR_CHAR_MAP = str.maketrans({
    "I": PALOCHKA, "І": PALOCHKA, "і": PALOCHKA,
    "Ї": PALOCHKA, "ї": PALOCHKA, "ӏ": PALOCHKA,
    "|": PALOCHKA, "!": PALOCHKA, "[": PALOCHKA, "]": PALOCHKA,
    "1": PALOCHKA,
})
CANON_EXTRA_MAP = str.maketrans({"T": PALOCHKA, "6": "б", "0": "о"})


def visible_clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").translate(OCR_CHAR_MAP)).strip()


def canon_token(s: str) -> str:
    s = visible_clean(s).translate(CANON_EXTRA_MAP).lower().replace("ё", "е")
    return re.sub(r"[^0-9а-яӀa-z]+", "", s, flags=re.IGNORECASE)


def token_similarity(a: str, b: str) -> float:
    ca, cb = canon_token(a), canon_token(b)
    if not ca or not cb:
        return 0.0
    if ca == cb:
        return 1.0
    return SequenceMatcher(None, ca, cb).ratio()


def tokenize(s: str) -> List[str]:
    return [m.group(0) for m in WORD_RE.finditer(s or "")]


def extract_bracketed(context: str) -> Optional[str]:
    m = BRACKET_RE.search(context or "")
    return visible_clean(m.group(1)) if m else None


def extract_neighbors(context: str, window: int = 6) -> Tuple[List[str], List[str], Optional[str]]:
    context = context or ""
    m = BRACKET_RE.search(context)
    if not m:
        toks = tokenize(context)
        return toks[-window:], [], None
    return tokenize(context[:m.start()])[-window:], tokenize(context[m.end():])[:window], visible_clean(m.group(1))


def read_csv(path: Path) -> Tuple[List[str], List[dict]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        return list(reader.fieldnames or []), list(reader)


def write_csv(path: Path, fieldnames: List[str], rows: List[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def split_docx_pages(path: Path) -> Dict[int, str]:
    if Document is None:
        raise SystemExit("Missing dependency: python-docx. Install: pip install python-docx")
    doc = Document(str(path))
    pages: Dict[int, List[str]] = defaultdict(list)
    current: Optional[int] = None
    for p in doc.paragraphs:
        text = (p.text or "").strip()
        if not text:
            continue
        if re.fullmatch(r"\d{1,4}", text):
            n = int(text)
            if 1 <= n <= 1000:
                current = n
                pages[current]
                continue
        if current is not None:
            pages[current].append(text)
    out: Dict[int, str] = {}
    for page, parts in pages.items():
        txt = "\n".join(parts)
        txt = re.sub(r"([А-Яа-яЁёІіЇїӀӏA-Za-z])[-–]\s*\n\s*([А-Яа-яЁёІіЇїӀӏA-Za-z])", r"\1\2", txt)
        txt = re.sub(r"\s+", " ", txt).strip()
        out[page] = visible_clean(txt)
    return out


def build_page_infos(pages: Dict[int, str]) -> Dict[int, dict]:
    infos = {}
    for page, text in pages.items():
        toks = [visible_clean(t) for t in tokenize(text)]
        pos_index = defaultdict(list)
        for i, tok in enumerate(toks):
            ct = canon_token(tok)
            if ct:
                pos_index[ct].append(i)
        infos[page] = {"text": text, "tokens": toks, "canon_set": set(pos_index.keys()), "pos_index": dict(pos_index), "canon_join": " " + " ".join(canon_token(t) for t in toks if canon_token(t)) + " "}
    return infos


def score_alignment(tokens: List[str], idx: int, before: List[str], after: List[str]) -> Tuple[float, int]:
    scores: List[float] = []
    hits = 0
    for off, raw_tok in enumerate(reversed(before), start=1):
        j = idx - off
        if j >= 0:
            sim = token_similarity(raw_tok, tokens[j])
            scores.append(sim)
            if sim >= 0.82:
                hits += 1
    for off, raw_tok in enumerate(after, start=1):
        j = idx + off
        if j < len(tokens):
            sim = token_similarity(raw_tok, tokens[j])
            scores.append(sim)
            if sim >= 0.82:
                hits += 1
    if not scores:
        return 0.0, 0
    return min(sum(scores) / len(scores) + min(hits, 6) * 0.06, 1.0), hits


def find_in_page(page_info: dict, before: List[str], after: List[str], target: str) -> Tuple[Optional[str], float, int]:
    tokens = page_info["tokens"]
    if not tokens:
        return None, 0.0, 0

    # Generate only likely target indices from positions of neighboring tokens.
    # This is much faster than scoring every token on every page.
    candidate_indices = set()
    pos_index = page_info.get("pos_index", {})
    for off, raw_tok in enumerate(reversed(before), start=1):
        ct = canon_token(raw_tok)
        for pos in pos_index.get(ct, [])[:50]:
            cand = pos + off
            if 0 <= cand < len(tokens):
                candidate_indices.add(cand)
    for off, raw_tok in enumerate(after, start=1):
        ct = canon_token(raw_tok)
        for pos in pos_index.get(ct, [])[:50]:
            cand = pos - off
            if 0 <= cand < len(tokens):
                candidate_indices.add(cand)

    # If no candidates from context, fall back only to target-like tokens.
    if not candidate_indices:
        target_c = canon_token(target)
        for i, tok in enumerate(tokens):
            if target_c and token_similarity(target, tok) >= 0.65:
                candidate_indices.add(i)

    # Hard cap for pathological pages.
    if len(candidate_indices) > 300:
        candidate_indices = set(list(candidate_indices)[:300])

    best = (-1.0, 0, -1)
    for i in candidate_indices:
        tok = tokens[i]
        score, hits = score_alignment(tokens, i, before, after)
        if token_similarity(target, tok) >= 0.65:
            score += 0.08
        if score > best[0]:
            best = (score, hits, i)
    score, hits, idx = best
    if idx >= 0 and score >= 0.72 and hits >= 3:
        return tokens[idx], min(score, 1.0), hits
    return None, max(score, 0.0), hits


def context_terms(before: List[str], after: List[str]) -> List[str]:
    return [canon_token(t) for t in before + after if canon_token(t)]


def _phrases(tokens: List[str], sizes=(5, 4, 3)) -> List[str]:
    c = [canon_token(t) for t in tokens if canon_token(t)]
    out = []
    for n in sizes:
        if len(c) >= n:
            out.append(" " + " ".join(c[-n:]) + " ")
            out.append(" " + " ".join(c[:n]) + " ")
    return [p for p in out if len(p.strip().split()) >= 3]


def find_across_pages(page_infos: Dict[int, dict], preferred_page: Optional[int], before: List[str], after: List[str], target: str) -> Tuple[Optional[int], Optional[str], float, int, str]:
    pages_to_try: List[int] = []
    if preferred_page in page_infos:
        pages_to_try.append(preferred_page)  # type: ignore[arg-type]

    phrases = _phrases(before) + _phrases(after)
    for p, info in page_infos.items():
        if p == preferred_page:
            continue
        cj = info.get("canon_join", "")
        if any(ph in cj for ph in phrases):
            pages_to_try.append(p)

    # Keep order but remove duplicates.
    seen = set()
    pages_to_try = [p for p in pages_to_try if not (p in seen or seen.add(p))]

    best = (None, None, 0.0, 0)  # page, token, score, hits
    for p in pages_to_try:
        tok, score, hits = find_in_page(page_infos[p], before, after, target)
        if score > best[2]:
            best = (p, tok, score, hits)
    page, tok, score, hits = best
    if tok is not None:
        return page, tok, score, hits, "context alignment"
    return page, None, score, hits, "context alignment weak"


def parse_candidates(candidates: str) -> List[str]:
    if not candidates or candidates.strip().lower() == "none":
        return []
    return [visible_clean(p) for p in re.split(r"[,;]\s*", candidates.strip()) if p.strip() and p.strip().lower() != "none"]


def append_note(old: str, add: str) -> str:
    old, add = (old or "").strip(), (add or "").strip()
    if not add:
        return old
    if not old:
        return add
    if add in old:
        return old
    return old + " | " + add


def plausible_replacement(word: str, manual_tok: str, corrected_tok: Optional[str], candidates: List[str]) -> bool:
    """Block obvious false alignments, e.g. long OCR token -> single-letter 'а'."""
    cw, cm = canon_token(word), canon_token(manual_tok)
    if not cw or not cm:
        return False
    if token_similarity(word, manual_tok) >= 0.45:
        return True
    if corrected_tok and token_similarity(corrected_tok, manual_tok) >= 0.70:
        return True
    if any(token_similarity(c, manual_tok) >= 0.70 for c in candidates):
        return True
    # Very short manual token cannot safely replace a longer suspicious token.
    if len(cm) <= 2 and len(cw) >= 4:
        return False
    return False


def decide_row(row: dict, page_infos: Dict[int, dict], overwrite: bool = False) -> Tuple[dict, str]:
    out = dict(row)
    if not overwrite and (out.get("decision") or "").strip() not in ("", "pending"):
        return out, "kept_existing"
    try:
        preferred_page = int((row.get("page") or "").strip())
    except ValueError:
        preferred_page = None

    word_orig = row.get("word", "") or ""
    word = visible_clean(word_orig)
    corrected_tok = extract_bracketed(row.get("corrected_context", ""))
    raw_before, raw_after, raw_target = extract_neighbors(row.get("raw_context", ""), window=6)
    if not raw_before and not raw_after:
        raw_before, raw_after, raw_target = extract_neighbors(row.get("corrected_context", ""), window=6)
    target = raw_target or word
    candidates = parse_candidates(row.get("candidates", ""))

    manual_page, manual_tok, score, hits, note = find_across_pages(page_infos, preferred_page, raw_before, raw_after, target)

    out["manual_page"] = "" if manual_page is None else str(manual_page)
    out["manual_match"] = manual_tok or ""

    if manual_tok:
        same_exact = manual_tok == word_orig
        same_canon = canon_token(manual_tok) == canon_token(word)
        if same_exact:
            out["decision"] = "reject"
            out["replacement"] = ""
            out["confidence"] = f"high:{score:.2f}"
            out["notes"] = append_note(out.get("notes", ""), f"manual DOCX: suspicious token preserved on manual page {manual_page}; {note} hits={hits}")
            return out, "reject_manual_same"
        if same_canon and manual_tok != word:
            # Same canonical token but with normalized palochka/characters: keep as replacement.
            out["decision"] = "replace"
            out["replacement"] = manual_tok
            out["confidence"] = f"high:{score:.2f}"
            out["notes"] = append_note(out.get("notes", ""), f"manual DOCX: normalized token on manual page {manual_page}; {note} hits={hits}")
            return out, "replace_normalized_same"
        if plausible_replacement(word, manual_tok, corrected_tok, candidates):
            out["decision"] = "replace"
            out["replacement"] = manual_tok
            out["confidence"] = f"high:{score:.2f}" if score >= 0.82 else f"medium:{score:.2f}"
            out["notes"] = append_note(out.get("notes", ""), f"manual DOCX: replacement by context on manual page {manual_page}; {note} hits={hits}")
            return out, "replace_context"
        out["decision"] = "pending"
        out["replacement"] = ""
        out["confidence"] = f"low:{score:.2f}"
        out["notes"] = append_note(out.get("notes", ""), f"manual DOCX: context found on manual page {manual_page}, but replacement not plausible: {manual_tok}; нужен оригинал страницы")
        return out, "pending_implausible"

    # Fallback: corrected token/candidate exists on some manual page with enough context overlap.
    if corrected_tok:
        # Look only at pages with context overlap to avoid unrelated common words.
        terms = context_terms(raw_before, raw_after)
        for p, info in page_infos.items():
            if sum(1 for t in terms if t in info["canon_set"]) >= 3 and canon_token(corrected_tok) in info["canon_set"]:
                if token_similarity(word, corrected_tok) >= 0.58:
                    out["decision"] = "replace"
                    out["replacement"] = corrected_tok
                    out["manual_page"] = str(p)
                    out["manual_match"] = corrected_tok
                    out["confidence"] = "medium:corrected_token_on_manual_page"
                    out["notes"] = append_note(out.get("notes", ""), f"manual DOCX: corrected token found on likely manual page {p}")
                    return out, "replace_corrected_token"

    out["decision"] = "pending"
    out["replacement"] = ""
    out["confidence"] = f"low:{score:.2f}"
    if manual_page is None:
        extra = "manual DOCX: no matching page/context found; нужен оригинал страницы"
    else:
        extra = f"manual DOCX: no confident match; best manual page {manual_page}; score={score:.2f}; hits={hits}; нужен оригинал страницы"
    out["notes"] = append_note(out.get("notes", ""), extra)
    return out, "pending_no_match"


def main() -> None:
    ap = argparse.ArgumentParser(description=f"Prefill suspicious review CSV from manually cleaned DOCX v{VERSION}")
    ap.add_argument("--base-dir", default=".")
    ap.add_argument("--review", default=None)
    ap.add_argument("--manual-docx", default=None)
    ap.add_argument("--out", default="suspicious_review_table_prefilled_from_manual_docx.csv")
    ap.add_argument("--report", default="manual_docx_prefill_report.txt")
    ap.add_argument("--overwrite", action="store_true")
    args = ap.parse_args()

    base = Path(args.base_dir)
    review = Path(args.review) if args.review else base / "output" / "suspicious_review_table_with_context.csv"
    docx = Path(args.manual_docx) if args.manual_docx else base / "output" / "recognized_text_after_70_pages (1).docx"
    if not review.exists():
        raise SystemExit(f"Review CSV not found: {review}")
    if not docx.exists():
        raise SystemExit(f"Manual DOCX not found: {docx}")

    fieldnames, rows = read_csv(review)
    for extra in ["manual_page", "manual_match", "confidence"]:
        if extra not in fieldnames:
            fieldnames.append(extra)

    pages = split_docx_pages(docx)
    page_infos = build_page_infos(pages)

    updated, stats = [], Counter()
    for row in rows:
        new_row, status = decide_row(row, page_infos, overwrite=args.overwrite)
        updated.append(new_row)
        stats[status] += 1

    out = Path(args.out)
    report = Path(args.report)
    write_csv(out, fieldnames, updated)

    decision_counts = Counter((r.get("decision") or "").strip() or "blank" for r in updated)
    confidence_counts = Counter((r.get("confidence") or "").split(":", 1)[0] or "blank" for r in updated)
    changed_page = sum(1 for r in updated if (r.get("manual_page") or "") and (r.get("page") or "") and r.get("manual_page") != r.get("page"))

    lines = [
        f"manual DOCX prefill report v{VERSION}",
        f"Review CSV: {review}",
        f"Manual DOCX: {docx}",
        f"Output CSV: {out}",
        f"Rows: {len(rows)}",
        f"Manual DOCX pages detected: {len(pages)} ({min(pages) if pages else ''}..{max(pages) if pages else ''})",
        f"Rows matched to a different manual page than review page: {changed_page}",
        "",
        "Status counts:",
    ]
    lines += [f"  {k}: {v}" for k, v in stats.most_common()]
    lines += ["", "Decision counts after prefill:"]
    lines += [f"  {k}: {v}" for k, v in decision_counts.most_common()]
    lines += ["", "Confidence groups:"]
    lines += [f"  {k}: {v}" for k, v in confidence_counts.most_common()]
    lines += ["", "Safety note:", "  This script only pre-fills review decisions. Verify medium/low confidence rows before applying replacements."]
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"Review CSV: {review}")
    print(f"Manual DOCX: {docx}")
    print(f"Manual pages detected: {len(pages)} ({min(pages) if pages else ''}..{max(pages) if pages else ''})")
    print(f"Created: {out}")
    print(f"Report: {report}")
    print(f"Rows: {len(rows)}")
    print("Decision counts:", dict(decision_counts))
    print("Status counts:", dict(stats))
    print(f"Rows matched to different manual page: {changed_page}")


if __name__ == "__main__":
    main()
