# -*- coding: utf-8 -*-
"""
compare_docx_vs_v54_by_printed_page.py

Compare DOCX text and V5.4 final output by printed page number.

Why this script exists:
- DOCX uses internal page breaks and printed page numbers.
- V5.4 uses OCR headers:
    ===== Страница 73 | IMG-....jpg =====
- Some printed pages have multiple image chunks in V5.4.
- Row-by-row comparison becomes misaligned.
- This script groups V5.4 chunks by printed page number and compares them
  with DOCX chunks that start with the same printed page number.

Typical command:

python compare_docx_vs_v54_by_printed_page.py --manual-docx "recognized_text_after_70_pages (1).docx" --v54-final output\recognized_text_ordered_chechen_fixed_reviewed_final_v4.txt --start-page 73 --out-dir output\compare_by_printed_page_73
"""

import argparse
import csv
import difflib
import re
import zipfile
from pathlib import Path
import xml.etree.ElementTree as ET

NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}

V54_PAGE_RE = re.compile(
    r"(?m)^=+\s*Страница\s+(?P<page>\d+|номер не распознан)\s*\|\s*(?P<img>[^=]+?)\s*=+\s*$"
)

PRINTED_PAGE_RE = re.compile(r"^\s*(\d{1,3})\s*$")

def write_txt(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")

def read_txt(path):
    return Path(path).read_text(encoding="utf-8-sig")

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
    text = V54_PAGE_RE.sub(" ", text)
    text = text.replace("<<<DOCX_PAGE_BREAK>>>", " ")
    text = re.sub(r"(?m)^\s*\d{1,3}\s*$", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()

def stats(text):
    return {
        "chars": len(text),
        "lines": text.count("\n") + 1 if text else 0,
        "words_est": len(re.findall(r"[А-Яа-яЁёӀӏІіЇїA-Za-z]+", text)),
        "Ӏ": text.count("Ӏ"),
        "I": text.count("I"),
        "Ї": text.count("Ї"),
        "!": text.count("!"),
        "|": text.count("|"),
        "[": text.count("["),
        "]": text.count("]"),
    }

def group_docx_by_printed_page(docx_text, start_page):
    chunks = docx_text.split("<<<DOCX_PAGE_BREAK>>>")
    grouped = {}
    unnumbered = []
    for idx, chunk in enumerate(chunks, start=1):
        first = first_nonempty_line(chunk)
        m = PRINTED_PAGE_RE.match(first)
        if not m:
            unnumbered.append((idx, first, chunk))
            continue
        page = int(m.group(1))
        if page < start_page:
            continue
        grouped.setdefault(page, []).append({
            "break_index": idx,
            "text": chunk,
            "first_line": first,
        })
    return grouped, unnumbered

def group_v54_by_page(v54_text, start_page):
    markers = list(V54_PAGE_RE.finditer(v54_text))
    grouped = {}
    unknown = []
    for i, m in enumerate(markers):
        page_raw = m.group("page")
        image = m.group("img").strip()
        start = m.start()
        end = markers[i + 1].start() if i + 1 < len(markers) else len(v54_text)
        chunk = v54_text[start:end]
        if not page_raw.isdigit():
            unknown.append({"image": image, "text": chunk})
            continue
        page = int(page_raw)
        if page < start_page:
            continue
        grouped.setdefault(page, []).append({
            "image": image,
            "text": chunk,
            "header": m.group(0),
        })
    return grouped, unknown

def make_diff_for_page(path, page, manual_text, v54_text, limit=800):
    diff = difflib.unified_diff(
        manual_text.splitlines(),
        v54_text.splitlines(),
        fromfile=f"DOCX_page_{page}",
        tofile=f"V54_page_{page}",
        lineterm="",
        n=3,
    )
    lines = []
    for i, line in enumerate(diff):
        if i >= limit:
            lines.append("... diff truncated ...")
            break
        lines.append(line)
    write_txt(path, "\n".join(lines) + "\n")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manual-docx", required=True)
    ap.add_argument("--v54-final", required=True)
    ap.add_argument("--start-page", type=int, default=73)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    diff_dir = out_dir / "page_diffs"
    diff_dir.mkdir(parents=True, exist_ok=True)

    print("Reading DOCX...")
    docx_text = extract_docx_text(args.manual_docx)
    print("Reading V5.4 final...")
    v54_text = read_txt(args.v54_final)

    docx_grouped, docx_unnumbered = group_docx_by_printed_page(docx_text, args.start_page)
    v54_grouped, v54_unknown = group_v54_by_page(v54_text, args.start_page)

    pages = sorted(set(docx_grouped.keys()) | set(v54_grouped.keys()))
    rows = []

    for page in pages:
        d_chunks = docx_grouped.get(page, [])
        v_chunks = v54_grouped.get(page, [])

        d_text = "\n<<<DOCX_PAGE_BREAK>>>\n".join(c["text"] for c in d_chunks)
        v_text = "\n".join(c["text"] for c in v_chunks)

        d_norm = normalize_for_compare(d_text)
        v_norm = normalize_for_compare(v_text)

        sim = difflib.SequenceMatcher(None, d_norm, v_norm).ratio() if (d_norm or v_norm) else 0.0
        d_stats = stats(d_text)
        v_stats = stats(v_text)

        diff_file = ""
        if d_text and v_text and sim < 0.985:
            diff_file = str(diff_dir / f"diff_page_{page}.txt")
            make_diff_for_page(diff_file, page, d_text, v_text)

        rows.append({
            "page": page,
            "docx_chunks": len(d_chunks),
            "v54_chunks": len(v_chunks),
            "v54_images": "; ".join(c["image"] for c in v_chunks),
            "docx_chars": d_stats["chars"],
            "v54_chars": v_stats["chars"],
            "similarity": f"{sim:.4f}",
            "docx_palochka": d_stats["Ӏ"],
            "v54_palochka": v_stats["Ӏ"],
            "docx_I": d_stats["I"],
            "v54_I": v_stats["I"],
            "docx_bang": d_stats["!"],
            "v54_bang": v_stats["!"],
            "docx_pipe": d_stats["|"],
            "v54_pipe": v_stats["|"],
            "docx_right_bracket": d_stats["]"],
            "v54_right_bracket": v_stats["]"],
            "diff_file": diff_file,
            "note": (
                "missing_in_docx" if not d_chunks else
                "missing_in_v54" if not v_chunks else
                "multi_v54_chunks" if len(v_chunks) > 1 else
                "ok"
            ),
        })

    csv_path = out_dir / "page_number_comparison.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        fieldnames = [
            "page", "docx_chunks", "v54_chunks", "v54_images",
            "docx_chars", "v54_chars", "similarity",
            "docx_palochka", "v54_palochka", "docx_I", "v54_I",
            "docx_bang", "v54_bang", "docx_pipe", "v54_pipe",
            "docx_right_bracket", "v54_right_bracket",
            "diff_file", "note",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    low = [r for r in rows if float(r["similarity"]) < 0.90]
    medium = [r for r in rows if 0.90 <= float(r["similarity"]) < 0.985]
    high = [r for r in rows if float(r["similarity"]) >= 0.985]
    missing_docx = [r for r in rows if r["note"] == "missing_in_docx"]
    missing_v54 = [r for r in rows if r["note"] == "missing_in_v54"]
    multi_v54 = [r for r in rows if r["v54_chunks"] > 1]

    docx_all = "\n".join("\n<<<DOCX_PAGE_BREAK>>>\n".join(c["text"] for c in docx_grouped[p]) for p in sorted(docx_grouped))
    v54_all = "\n".join("\n".join(c["text"] for c in v54_grouped[p]) for p in sorted(v54_grouped))
    global_sim = difflib.SequenceMatcher(None, normalize_for_compare(docx_all), normalize_for_compare(v54_all)).ratio()

    report = []
    report.append("compare_docx_vs_v54_by_printed_page.py report")
    report.append("")
    report.append(f"Manual DOCX: {args.manual_docx}")
    report.append(f"V5.4 final TXT: {args.v54_final}")
    report.append(f"Start printed page: {args.start_page}")
    report.append("")
    report.append(f"DOCX pages found from start: {len(docx_grouped)}")
    report.append(f"V5.4 pages found from start: {len(v54_grouped)}")
    report.append(f"V5.4 unknown page chunks: {len(v54_unknown)}")
    report.append("")
    report.append(f"Global normalized similarity by grouped printed pages: {global_sim:.4f}")
    report.append(f"Rows/pages: {len(rows)}")
    report.append(f"Pages similarity >= 0.985: {len(high)}")
    report.append(f"Pages similarity 0.900..0.984: {len(medium)}")
    report.append(f"Pages similarity < 0.900: {len(low)}")
    report.append(f"Pages missing in DOCX: {len(missing_docx)}")
    report.append(f"Pages missing in V5.4: {len(missing_v54)}")
    report.append(f"Pages with multiple V5.4 chunks: {len(multi_v54)}")
    report.append("")
    report.append("Top pages with multiple V5.4 chunks:")
    for r in multi_v54[:40]:
        report.append(f"  page={r['page']} v54_chunks={r['v54_chunks']} images={r['v54_images']} similarity={r['similarity']}")
    report.append("")
    report.append("Lowest similarity pages:")
    for r in sorted(rows, key=lambda x: float(x["similarity"]))[:50]:
        report.append(
            f"  page={r['page']} sim={r['similarity']} docx_chars={r['docx_chars']} "
            f"v54_chars={r['v54_chars']} docx_chunks={r['docx_chunks']} v54_chunks={r['v54_chunks']} note={r['note']}"
        )
    report.append("")
    report.append("Created:")
    report.append(f"  {csv_path}")
    report.append(f"  {diff_dir}")
    report.append(f"  {out_dir / 'comparison_report.txt'}")
    report.append("")
    report.append("Interpretation:")
    report.append("  - This comparison is safer than row-by-row comparison because it groups by printed page number.")
    report.append("  - A low score can mean V5.4 has extra image chunks for the same printed page, DOCX is missing chunks, or the OCR texts differ strongly.")
    report.append("  - Do not replace DOCX globally without reviewing page_number_comparison.csv and the page_diffs folder.")

    write_txt(out_dir / "comparison_report.txt", "\n".join(report) + "\n")

    print("Created:", out_dir / "comparison_report.txt")
    print("Created:", csv_path)
    print("Created:", diff_dir)
    print("")
    print(f"Global normalized similarity by grouped printed pages: {global_sim:.4f}")
    print(f"Pages similarity >= 0.985: {len(high)}")
    print(f"Pages similarity 0.900..0.984: {len(medium)}")
    print(f"Pages similarity < 0.900: {len(low)}")
    print(f"Pages missing in DOCX: {len(missing_docx)}")
    print(f"Pages missing in V5.4: {len(missing_v54)}")
    print(f"Pages with multiple V5.4 chunks: {len(multi_v54)}")

if __name__ == "__main__":
    main()
