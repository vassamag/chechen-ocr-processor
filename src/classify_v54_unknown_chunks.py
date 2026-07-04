# -*- coding: utf-8 -*-
"""
classify_v54_unknown_chunks.py

Find and classify V5.4 OCR chunks whose printed page number was not recognized.
This is for the case where a bad scan captured part of a neighboring page and OCR
created a fake "page" chunk without a visible page number.

The script does NOT change any text.
It creates:
- unknown_chunks_report.txt
- unknown_chunks_mapping.csv
- unknown_chunks/unknown_###.txt

Typical command:

python classify_v54_unknown_chunks.py --manual-docx "recognized_text_after_70_pages (1).docx" --v54-final output\recognized_text_ordered_chechen_fixed_reviewed_final_v4.txt --start-page 73 --out-dir output\classify_v54_unknown_chunks
"""

import argparse
import csv
import difflib
import re
import zipfile
from pathlib import Path
import xml.etree.ElementTree as ET

NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}

V54_HEADER_RE = re.compile(
    r"(?m)^=+\s*Страница\s+(?P<page>\d+|номер не распознан)\s*\|\s*(?P<img>[^=]+?)\s*=+\s*$"
)

PRINTED_PAGE_RE = re.compile(r"^\s*(\d{1,3})\s*$")

CYR_RE = re.compile(r"[А-Яа-яЁёӀӏІіЇї]")
WORD_RE = re.compile(r"[А-Яа-яЁёӀӏІіЇїA-Za-z]+", re.UNICODE)

def read_txt(path):
    return Path(path).read_text(encoding="utf-8-sig")

def write_txt(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")

def extract_docx_text(docx_path):
    with zipfile.ZipFile(docx_path) as z:
        xml = z.read("word/document.xml")
    root = ET.fromstring(xml)
    body = root.find("w:body", NS)

    out = []
    for p in body.iterfind(".//w:p", NS):
        parts = []
        for node in p.iter():
            tag = node.tag.split("}")[-1]
            if tag == "t":
                parts.append(node.text or "")
            elif tag == "tab":
                parts.append("\t")
            elif tag == "br":
                br_type = node.attrib.get("{" + NS["w"] + "}type", "")
                if br_type == "page":
                    parts.append("\n<<<DOCX_PAGE_BREAK>>>\n")
                else:
                    parts.append("\n")
            elif tag == "lastRenderedPageBreak":
                parts.append("\n<<<DOCX_PAGE_BREAK>>>\n")
        out.append("".join(parts))

    text = "\n".join(out)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"(?:\n*<<<DOCX_PAGE_BREAK>>>\n*)+", "\n<<<DOCX_PAGE_BREAK>>>\n", text)
    return text

def first_nonempty_line(text):
    for line in text.splitlines():
        s = line.strip()
        if s:
            return s
    return ""

def normalize_for_compare(text):
    text = V54_HEADER_RE.sub(" ", text)
    text = text.replace("<<<DOCX_PAGE_BREAK>>>", " ")
    text = re.sub(r"(?m)^\s*\d{1,3}\s*$", " ", text)
    text = re.sub(r"[*()«»\"“”№©ў]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()

def stats(text):
    chars = len(text)
    words = WORD_RE.findall(text)
    cyr = CYR_RE.findall(text)
    lines = text.count("\n") + 1 if text else 0
    return {
        "chars": chars,
        "lines": lines,
        "words": len(words),
        "cyr_chars": len(cyr),
        "cyr_ratio": (len(cyr) / chars) if chars else 0.0,
        "palochka": text.count("Ӏ"),
        "bang": text.count("!"),
        "pipe": text.count("|"),
        "right_bracket": text.count("]"),
    }

def group_docx_pages(docx_text, start_page):
    chunks = docx_text.split("<<<DOCX_PAGE_BREAK>>>")
    pages = {}
    for idx, chunk in enumerate(chunks, start=1):
        first = first_nonempty_line(chunk)
        m = PRINTED_PAGE_RE.match(first)
        if not m:
            continue
        page = int(m.group(1))
        if page < start_page:
            continue
        pages.setdefault(page, []).append({"break_index": idx, "text": chunk})
    # merge chunks per page
    merged = {}
    for page, items in pages.items():
        merged[page] = "\n<<<DOCX_PAGE_BREAK>>>\n".join(x["text"] for x in items)
    return merged

def parse_v54_chunks(v54_text):
    markers = list(V54_HEADER_RE.finditer(v54_text))
    chunks = []
    for i, m in enumerate(markers):
        page_raw = m.group("page")
        img = m.group("img").strip()
        start = m.start()
        end = markers[i + 1].start() if i + 1 < len(markers) else len(v54_text)
        text = v54_text[start:end]
        page_num = int(page_raw) if page_raw.isdigit() else None
        chunks.append({
            "index": i + 1,
            "page_raw": page_raw,
            "page_num": page_num,
            "image": img,
            "text": text,
            "header": m.group(0),
        })
    return chunks

def group_known_v54_pages(chunks, start_page):
    pages = {}
    for ch in chunks:
        if ch["page_num"] is None:
            continue
        if ch["page_num"] < start_page:
            continue
        pages.setdefault(ch["page_num"], []).append(ch["text"])
    return {p: "\n".join(items) for p, items in pages.items()}

def best_similarity(query_text, candidates):
    q = normalize_for_compare(query_text)
    if not q:
        return None, 0.0
    best_key = None
    best_score = 0.0
    for key, text in candidates.items():
        c = normalize_for_compare(text)
        if not c:
            continue
        score = difflib.SequenceMatcher(None, q, c).ratio()
        if score > best_score:
            best_key = key
            best_score = score
    return best_key, best_score

def best_substring_similarity(query_text, candidate_text):
    """
    Estimate whether query_text is a fragment of candidate_text.
    Uses word-window search around the same length as query.
    """
    q = normalize_for_compare(query_text)
    c = normalize_for_compare(candidate_text)
    if not q or not c:
        return 0.0

    q_words = q.split()
    c_words = c.split()
    if not q_words or not c_words:
        return 0.0

    qn = len(q_words)
    if qn >= len(c_words):
        return difflib.SequenceMatcher(None, q, c).ratio()

    # For speed: compare windows approximately query length.
    step = max(1, qn // 6)
    best = 0.0
    for start in range(0, max(1, len(c_words) - qn + 1), step):
        window = " ".join(c_words[start:start + qn])
        score = difflib.SequenceMatcher(None, q, window).ratio()
        if score > best:
            best = score
    return best

def best_fragment_match(query_text, candidates):
    best_key = None
    best_score = 0.0
    for key, text in candidates.items():
        score = best_substring_similarity(query_text, text)
        if score > best_score:
            best_key = key
            best_score = score
    return best_key, best_score

def classify_row(st, best_docx_sim, best_docx_fragment_sim, best_known_sim, best_known_fragment_sim):
    # Very small or mostly non-Cyrillic chunks are usually OCR garbage.
    if st["chars"] < 120 or st["words"] < 10:
        return "tiny_or_noise"

    if st["cyr_ratio"] < 0.35:
        return "likely_ocr_garbage_or_fake_page"

    # If the entire unknown chunk is very close to a known V54 page, it is likely duplicated/neighbor capture.
    if best_known_sim >= 0.90 or best_known_fragment_sim >= 0.92:
        return "duplicate_or_neighbor_fragment_of_known_v54_page"

    # If it matches a DOCX printed page fragment, it probably belongs to that printed page.
    if best_docx_sim >= 0.85 or best_docx_fragment_sim >= 0.90:
        return "assignable_to_docx_printed_page"

    if best_docx_fragment_sim >= 0.75:
        return "possible_partial_neighbor_page"

    return "unresolved_manual_review"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manual-docx", required=True)
    ap.add_argument("--v54-final", required=True)
    ap.add_argument("--start-page", type=int, default=73)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    chunks_dir = out_dir / "unknown_chunks"
    out_dir.mkdir(parents=True, exist_ok=True)
    chunks_dir.mkdir(parents=True, exist_ok=True)

    print("Reading DOCX...")
    docx_text = extract_docx_text(args.manual_docx)
    print("Reading V5.4 final...")
    v54_text = read_txt(args.v54_final)

    docx_pages = group_docx_pages(docx_text, args.start_page)
    v54_chunks = parse_v54_chunks(v54_text)
    known_v54_pages = group_known_v54_pages(v54_chunks, args.start_page)
    unknown_chunks = [c for c in v54_chunks if c["page_num"] is None]

    rows = []
    class_counts = {}

    for u_no, ch in enumerate(unknown_chunks, start=1):
        text = ch["text"]
        st = stats(text)

        best_docx_page, best_docx_sim = best_similarity(text, docx_pages)
        best_docx_frag_page, best_docx_frag_sim = best_fragment_match(text, docx_pages)

        best_known_page, best_known_sim = best_similarity(text, known_v54_pages)
        best_known_frag_page, best_known_frag_sim = best_fragment_match(text, known_v54_pages)

        cls = classify_row(st, best_docx_sim, best_docx_frag_sim, best_known_sim, best_known_frag_sim)
        class_counts[cls] = class_counts.get(cls, 0) + 1

        chunk_file = chunks_dir / f"unknown_{u_no:03d}_{ch['image']}.txt"
        # Windows may not like some characters; sanitize filename.
        chunk_file = Path(str(chunk_file).replace(":", "_").replace("/", "_").replace("\\", "_"))
        if not chunk_file.is_absolute():
            chunk_file = chunks_dir / f"unknown_{u_no:03d}.txt"
        write_txt(chunk_file, text)

        rows.append({
            "unknown_no": u_no,
            "v54_chunk_index": ch["index"],
            "image": ch["image"],
            "chars": st["chars"],
            "lines": st["lines"],
            "words": st["words"],
            "cyr_ratio": f"{st['cyr_ratio']:.3f}",
            "palochka": st["palochka"],
            "bang": st["bang"],
            "pipe": st["pipe"],
            "right_bracket": st["right_bracket"],
            "classification": cls,
            "best_docx_page": best_docx_page if best_docx_page is not None else "",
            "best_docx_similarity": f"{best_docx_sim:.4f}",
            "best_docx_fragment_page": best_docx_frag_page if best_docx_frag_page is not None else "",
            "best_docx_fragment_similarity": f"{best_docx_frag_sim:.4f}",
            "best_known_v54_page": best_known_page if best_known_page is not None else "",
            "best_known_v54_similarity": f"{best_known_sim:.4f}",
            "best_known_v54_fragment_page": best_known_frag_page if best_known_frag_page is not None else "",
            "best_known_v54_fragment_similarity": f"{best_known_frag_sim:.4f}",
            "chunk_file": str(chunk_file),
        })

    csv_path = out_dir / "unknown_chunks_mapping.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        fieldnames = [
            "unknown_no", "v54_chunk_index", "image",
            "chars", "lines", "words", "cyr_ratio",
            "palochka", "bang", "pipe", "right_bracket",
            "classification",
            "best_docx_page", "best_docx_similarity",
            "best_docx_fragment_page", "best_docx_fragment_similarity",
            "best_known_v54_page", "best_known_v54_similarity",
            "best_known_v54_fragment_page", "best_known_v54_fragment_similarity",
            "chunk_file",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    report = []
    report.append("classify_v54_unknown_chunks.py report")
    report.append("")
    report.append(f"Manual DOCX: {args.manual_docx}")
    report.append(f"V5.4 final TXT: {args.v54_final}")
    report.append(f"Start page: {args.start_page}")
    report.append("")
    report.append(f"DOCX printed pages available: {len(docx_pages)}")
    report.append(f"Known-number V5.4 pages available: {len(known_v54_pages)}")
    report.append(f"Total V5.4 chunks: {len(v54_chunks)}")
    report.append(f"Unknown-number V5.4 chunks: {len(unknown_chunks)}")
    report.append("")
    report.append("Classification counts:")
    for k, v in sorted(class_counts.items()):
        report.append(f"  {k}: {v}")
    report.append("")
    report.append("Top assignable/possible unknown chunks:")
    interesting = [
        r for r in rows
        if r["classification"] in ("assignable_to_docx_printed_page", "possible_partial_neighbor_page", "duplicate_or_neighbor_fragment_of_known_v54_page")
    ]
    for r in interesting[:80]:
        report.append(
            f"  unknown={r['unknown_no']} img={r['image']} class={r['classification']} "
            f"best_docx_page={r['best_docx_page']} docx_sim={r['best_docx_similarity']} "
            f"docx_frag_page={r['best_docx_fragment_page']} docx_frag_sim={r['best_docx_fragment_similarity']} "
            f"known_v54_page={r['best_known_v54_page']} known_sim={r['best_known_v54_similarity']} "
            f"known_frag_page={r['best_known_v54_fragment_page']} known_frag_sim={r['best_known_v54_fragment_similarity']}"
        )
    report.append("")
    report.append("Created:")
    report.append(f"  {csv_path}")
    report.append(f"  {chunks_dir}")
    report.append(f"  {out_dir / 'unknown_chunks_report.txt'}")
    report.append("")
    report.append("Interpretation:")
    report.append("  - assignable_to_docx_printed_page: likely belongs to an actual printed page.")
    report.append("  - duplicate_or_neighbor_fragment_of_known_v54_page: likely a fake/duplicate chunk caused by neighboring page capture.")
    report.append("  - likely_ocr_garbage_or_fake_page: probably not safe for automatic insertion.")
    report.append("  - unresolved_manual_review: needs human/JPG review.")
    report.append("  - This script does not modify DOCX or V5.4 output.")

    write_txt(out_dir / "unknown_chunks_report.txt", "\n".join(report) + "\n")

    print("Created:", out_dir / "unknown_chunks_report.txt")
    print("Created:", csv_path)
    print("Created:", chunks_dir)
    print("")
    print(f"Unknown-number V5.4 chunks: {len(unknown_chunks)}")
    print("Classification counts:")
    for k, v in sorted(class_counts.items()):
        print(f"  {k}: {v}")

if __name__ == "__main__":
    main()
