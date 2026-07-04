# -*- coding: utf-8 -*-
"""
compare_docx_vs_v54_with_unknown_mapping.py

Build a safer DOCX-vs-V5.4 page comparison after classifying
"номер не распознан" V5.4 chunks.

This script:
1. groups V5.4 chunks with recognized page numbers by page;
2. reads unknown_chunks_mapping.csv;
3. adds only high-confidence assignable unknown chunks to their best DOCX page;
4. compares DOCX printed pages 73+ against this reconstructed V5.4 page map.

It does NOT modify DOCX or V5.4 text.

Typical command:

python compare_docx_vs_v54_with_unknown_mapping.py ^
  --manual-docx "recognized_text_after_70_pages (1).docx" ^
  --v54-final output\recognized_text_ordered_chechen_fixed_reviewed_final_v4.txt ^
  --unknown-map output\classify_v54_unknown_chunks\unknown_chunks_mapping.csv ^
  --start-page 73 ^
  --out-dir output\compare_by_page_with_unknowns_73

Optional:
  --include-possible-partials
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

def group_docx_by_printed_page(docx_text, start_page):
    chunks = docx_text.split("<<<DOCX_PAGE_BREAK>>>")
    grouped = {}
    for idx, chunk in enumerate(chunks, start=1):
        first = first_nonempty_line(chunk)
        m = PRINTED_PAGE_RE.match(first)
        if not m:
            continue
        page = int(m.group(1))
        if page < start_page:
            continue
        grouped.setdefault(page, []).append({
            "break_index": idx,
            "text": chunk,
            "first_line": first,
        })
    return {
        page: "\n<<<DOCX_PAGE_BREAK>>>\n".join(item["text"] for item in items)
        for page, items in grouped.items()
    }

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

def normalize_for_compare(text):
    text = V54_HEADER_RE.sub(" ", text)
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

def load_unknown_map(path, include_possible_partials=False):
    allowed = {"assignable_to_docx_printed_page"}
    if include_possible_partials:
        allowed.add("possible_partial_neighbor_page")

    mapping = {}
    all_rows = []
    with Path(path).open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            all_rows.append(row)
            cls = row.get("classification", "")
            if cls not in allowed:
                continue
            page_raw = row.get("best_docx_page", "").strip()
            if not page_raw.isdigit():
                continue
            unknown_no = row.get("unknown_no", "").strip()
            if not unknown_no.isdigit():
                continue
            mapping[int(unknown_no)] = {
                "page": int(page_raw),
                "classification": cls,
                "image": row.get("image", ""),
                "best_docx_similarity": row.get("best_docx_similarity", ""),
            }
    return mapping, all_rows

def make_diff_for_page(path, page, docx_text, v54_text, limit=800):
    diff = difflib.unified_diff(
        docx_text.splitlines(),
        v54_text.splitlines(),
        fromfile=f"DOCX_page_{page}",
        tofile=f"V54_reconstructed_page_{page}",
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
    ap.add_argument("--unknown-map", required=True)
    ap.add_argument("--start-page", type=int, default=73)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--include-possible-partials", action="store_true")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    diff_dir = out_dir / "page_diffs"
    reconstructed_dir = out_dir / "reconstructed_v54_pages"
    out_dir.mkdir(parents=True, exist_ok=True)
    diff_dir.mkdir(parents=True, exist_ok=True)
    reconstructed_dir.mkdir(parents=True, exist_ok=True)

    print("Reading DOCX...")
    docx_text = extract_docx_text(args.manual_docx)
    print("Reading V5.4 final...")
    v54_text = read_txt(args.v54_final)
    print("Reading unknown mapping...")
    unknown_mapping, unknown_all_rows = load_unknown_map(args.unknown_map, args.include_possible_partials)

    docx_pages = group_docx_by_printed_page(docx_text, args.start_page)
    v54_chunks = parse_v54_chunks(v54_text)

    v54_pages = {}
    v54_page_images = {}
    unknown_no = 0
    assigned_unknown_count = 0
    skipped_unknown_count = 0

    for ch in v54_chunks:
        if ch["page_num"] is not None:
            if ch["page_num"] >= args.start_page:
                page = ch["page_num"]
                v54_pages.setdefault(page, []).append(ch["text"])
                v54_page_images.setdefault(page, []).append(ch["image"])
            continue

        unknown_no += 1
        if unknown_no in unknown_mapping:
            page = unknown_mapping[unknown_no]["page"]
            if page >= args.start_page:
                marker = (
                    "\n"
                    f"===== ASSIGNED UNKNOWN CHUNK {unknown_no} | {ch['image']} "
                    f"| class={unknown_mapping[unknown_no]['classification']} "
                    f"| best_docx_similarity={unknown_mapping[unknown_no]['best_docx_similarity']} =====\n"
                )
                v54_pages.setdefault(page, []).append(marker + ch["text"])
                v54_page_images.setdefault(page, []).append(f"UNKNOWN:{ch['image']}")
                assigned_unknown_count += 1
            else:
                skipped_unknown_count += 1
        else:
            skipped_unknown_count += 1

    v54_pages_joined = {p: "\n".join(items) for p, items in v54_pages.items()}

    pages = sorted(set(docx_pages.keys()) | set(v54_pages_joined.keys()))
    rows = []

    for page in pages:
        d_text = docx_pages.get(page, "")
        v_text = v54_pages_joined.get(page, "")

        sim = difflib.SequenceMatcher(None, normalize_for_compare(d_text), normalize_for_compare(v_text)).ratio() if (d_text or v_text) else 0.0
        ds = stats(d_text)
        vs = stats(v_text)

        diff_file = ""
        if d_text and v_text and sim < 0.985:
            diff_file = str(diff_dir / f"diff_page_{page}.txt")
            make_diff_for_page(diff_file, page, d_text, v_text)

        if v_text:
            write_txt(reconstructed_dir / f"v54_reconstructed_page_{page}.txt", v_text)

        rows.append({
            "page": page,
            "docx_chars": ds["chars"],
            "v54_chars": vs["chars"],
            "similarity": f"{sim:.4f}",
            "v54_images": "; ".join(v54_page_images.get(page, [])),
            "docx_palochka": ds["Ӏ"],
            "v54_palochka": vs["Ӏ"],
            "docx_I": ds["I"],
            "v54_I": vs["I"],
            "docx_bang": ds["!"],
            "v54_bang": vs["!"],
            "docx_pipe": ds["|"],
            "v54_pipe": vs["|"],
            "docx_right_bracket": ds["]"],
            "v54_right_bracket": vs["]"],
            "diff_file": diff_file,
            "note": (
                "missing_in_docx" if not d_text else
                "missing_in_v54_reconstructed" if not v_text else
                "ok"
            ),
        })

    csv_path = out_dir / "page_comparison_with_unknowns.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        fieldnames = [
            "page", "docx_chars", "v54_chars", "similarity", "v54_images",
            "docx_palochka", "v54_palochka", "docx_I", "v54_I",
            "docx_bang", "v54_bang", "docx_pipe", "v54_pipe",
            "docx_right_bracket", "v54_right_bracket", "diff_file", "note"
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    high = [r for r in rows if float(r["similarity"]) >= 0.985]
    medium = [r for r in rows if 0.90 <= float(r["similarity"]) < 0.985]
    low = [r for r in rows if float(r["similarity"]) < 0.90]
    missing_v54 = [r for r in rows if r["note"] == "missing_in_v54_reconstructed"]
    missing_docx = [r for r in rows if r["note"] == "missing_in_docx"]

    docx_all = "\n".join(docx_pages[p] for p in sorted(docx_pages))
    v54_all = "\n".join(v54_pages_joined[p] for p in sorted(v54_pages_joined))
    global_sim = difflib.SequenceMatcher(None, normalize_for_compare(docx_all), normalize_for_compare(v54_all)).ratio()

    report = []
    report.append("compare_docx_vs_v54_with_unknown_mapping.py report")
    report.append("")
    report.append(f"Manual DOCX: {args.manual_docx}")
    report.append(f"V5.4 final TXT: {args.v54_final}")
    report.append(f"Unknown mapping CSV: {args.unknown_map}")
    report.append(f"Start page: {args.start_page}")
    report.append(f"Include possible partials: {args.include_possible_partials}")
    report.append("")
    report.append(f"DOCX pages: {len(docx_pages)}")
    report.append(f"V5.4 reconstructed pages: {len(v54_pages_joined)}")
    report.append(f"Unknown chunks assigned: {assigned_unknown_count}")
    report.append(f"Unknown chunks skipped: {skipped_unknown_count}")
    report.append("")
    report.append(f"Global normalized similarity: {global_sim:.4f}")
    report.append(f"Rows/pages: {len(rows)}")
    report.append(f"Pages similarity >= 0.985: {len(high)}")
    report.append(f"Pages similarity 0.900..0.984: {len(medium)}")
    report.append(f"Pages similarity < 0.900: {len(low)}")
    report.append(f"Pages missing in reconstructed V5.4: {len(missing_v54)}")
    report.append(f"Pages missing in DOCX: {len(missing_docx)}")
    report.append("")
    report.append("Pages missing in reconstructed V5.4:")
    report.append("  " + ", ".join(str(r["page"]) for r in missing_v54))
    report.append("")
    report.append("Lowest similarity pages:")
    for r in sorted(rows, key=lambda x: float(x["similarity"]))[:60]:
        report.append(
            f"  page={r['page']} sim={r['similarity']} docx_chars={r['docx_chars']} "
            f"v54_chars={r['v54_chars']} note={r['note']} images={r['v54_images']}"
        )
    report.append("")
    report.append("Created:")
    report.append(f"  {csv_path}")
    report.append(f"  {diff_dir}")
    report.append(f"  {reconstructed_dir}")
    report.append(f"  {out_dir / 'comparison_report.txt'}")
    report.append("")
    report.append("Interpretation:")
    report.append("  - This is still a diagnostic report, not an automatic DOCX replacement.")
    report.append("  - Only assignable unknown chunks are included by default.")
    report.append("  - Possible partial neighbor pages are excluded unless --include-possible-partials is used.")
    report.append("  - Use page_comparison_with_unknowns.csv and page_diffs for manual audit.")

    write_txt(out_dir / "comparison_report.txt", "\n".join(report) + "\n")

    print("Created:", out_dir / "comparison_report.txt")
    print("Created:", csv_path)
    print("Created:", diff_dir)
    print("Created:", reconstructed_dir)
    print("")
    print(f"DOCX pages: {len(docx_pages)}")
    print(f"V5.4 reconstructed pages: {len(v54_pages_joined)}")
    print(f"Unknown chunks assigned: {assigned_unknown_count}")
    print(f"Unknown chunks skipped: {skipped_unknown_count}")
    print(f"Global normalized similarity: {global_sim:.4f}")
    print(f"Pages similarity >= 0.985: {len(high)}")
    print(f"Pages similarity 0.900..0.984: {len(medium)}")
    print(f"Pages similarity < 0.900: {len(low)}")
    print(f"Pages missing in reconstructed V5.4: {len(missing_v54)}")

if __name__ == "__main__":
    main()
