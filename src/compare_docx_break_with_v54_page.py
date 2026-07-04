# -*- coding: utf-8 -*-
import argparse
import csv
import difflib
import re
import zipfile
from pathlib import Path
import xml.etree.ElementTree as ET

NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}

PAGE_RE = re.compile(
    r"(?m)^=+\s*Страница\s+(?P<page>\d+|номер не распознан)\s*\|\s*(?P<img>[^=]+?)\s*=+\s*$"
)

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

def extract_docx_by_break(docx_text, break_start):
    pages = docx_text.split("<<<DOCX_PAGE_BREAK>>>")
    if break_start < 1 or break_start > len(pages):
        raise SystemExit(f"DOCX break_start is out of range: {break_start}; total breaks/pages: {len(pages)}")
    return "<<<DOCX_PAGE_BREAK>>>".join(pages[break_start - 1:]), len(pages)

def find_v54_markers(text):
    out = []
    for m in PAGE_RE.finditer(text):
        p = m.group("page")
        out.append({
            "start": m.start(),
            "end": m.end(),
            "page_raw": p,
            "page_num": int(p) if p.isdigit() else None,
            "image": m.group("img").strip(),
            "header": m.group(0),
        })
    return out

def extract_v54_from_page(text, start_page):
    markers = find_v54_markers(text)
    for m in markers:
        if m["page_num"] is not None and m["page_num"] >= start_page:
            return text[m["start"]:], str(m["page_num"])
    raise SystemExit(f"Could not find v54 page marker >= {start_page}")

def norm(text):
    text = PAGE_RE.sub(" ", text)
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

def docx_segments_by_break(text, start_break):
    pages = text.split("<<<DOCX_PAGE_BREAK>>>")
    segs = []
    for idx, pg in enumerate(pages, start=start_break):
        first = first_nonempty_line(pg)
        page_num = int(first) if re.fullmatch(r"\d{1,3}", first) else None
        segs.append({
            "break_index": idx,
            "page_raw": first if page_num is not None else "",
            "page_num": page_num,
            "text": pg,
        })
    return segs

def v54_segments(text):
    markers = find_v54_markers(text)
    segs = []
    for i, m in enumerate(markers):
        start = m["start"]
        end = markers[i + 1]["start"] if i + 1 < len(markers) else len(text)
        segs.append({
            "page_raw": m["page_raw"],
            "page_num": m["page_num"],
            "image": m["image"],
            "text": text[start:end],
        })
    return segs

def write_page_csv(path, manual_text, manual_break_start, v54_text):
    mseg = docx_segments_by_break(manual_text, manual_break_start)
    vseg = v54_segments(v54_text)

    rows = []
    max_len = max(len(mseg), len(vseg))
    for i in range(max_len):
        mt = mseg[i]["text"] if i < len(mseg) else ""
        vt = vseg[i]["text"] if i < len(vseg) else ""
        sim = difflib.SequenceMatcher(None, norm(mt), norm(vt)).ratio()
        rows.append({
            "row": i + 1,
            "manual_break": mseg[i]["break_index"] if i < len(mseg) else "",
            "manual_printed_page": mseg[i]["page_raw"] if i < len(mseg) else "",
            "v54_page": vseg[i]["page_raw"] if i < len(vseg) else "",
            "v54_image": vseg[i]["image"] if i < len(vseg) else "",
            "manual_chars": len(mt),
            "v54_chars": len(vt),
            "similarity": f"{sim:.4f}",
        })

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "row", "manual_break", "manual_printed_page", "v54_page", "v54_image",
            "manual_chars", "v54_chars", "similarity"
        ])
        writer.writeheader()
        writer.writerows(rows)
    return rows

def make_diff(path, manual_text, v54_text, limit):
    diff = difflib.unified_diff(
        manual_text.splitlines(),
        v54_text.splitlines(),
        fromfile="DOCX_manual_break",
        tofile="V54_page_marker",
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
    ap.add_argument("--manual-break-start", type=int, required=True,
                    help="DOCX page-break index to start from. For your file, 62 should correspond to printed page 73.")
    ap.add_argument("--v54-start-page", type=int, default=73)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--diff-max-lines", type=int, default=12000)
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("Reading DOCX...")
    docx_all = extract_docx_text(args.manual_docx)
    print("Reading v5.4 final...")
    v54_all = read_txt(args.v54_final)

    manual_part, total_docx_pages = extract_docx_by_break(docx_all, args.manual_break_start)
    v54_part, v54_found = extract_v54_from_page(v54_all, args.v54_start_page)

    write_txt(out_dir / f"manual_docx_from_break_{args.manual_break_start}.txt", manual_part)
    write_txt(out_dir / f"v54_from_page_{args.v54_start_page}.txt", v54_part)

    rows = write_page_csv(out_dir / "page_comparison.csv", manual_part, args.manual_break_start, v54_part)
    make_diff(out_dir / "diff_sample.txt", manual_part, v54_part, args.diff_max_lines)

    global_sim = difflib.SequenceMatcher(None, norm(manual_part), norm(v54_part)).ratio()
    low = [r for r in rows if float(r["similarity"]) < 0.80]
    very_low = [r for r in rows if float(r["similarity"]) < 0.50]

    report = []
    report.append("compare_docx_break_with_v54_page.py report")
    report.append("")
    report.append(f"Manual DOCX: {args.manual_docx}")
    report.append(f"V5.4 final TXT: {args.v54_final}")
    report.append(f"Manual DOCX break start: {args.manual_break_start}")
    report.append(f"Manual first non-empty line: {first_nonempty_line(manual_part)}")
    report.append(f"DOCX total page-break chunks: {total_docx_pages}")
    report.append(f"V54 start page requested: {args.v54_start_page}")
    report.append(f"V54 first page found: {v54_found}")
    report.append("")
    report.append("Manual DOCX stats:")
    for k, v in stats(manual_part).items():
        report.append(f"  {k}: {v}")
    report.append("")
    report.append("V5.4 stats:")
    for k, v in stats(v54_part).items():
        report.append(f"  {k}: {v}")
    report.append("")
    report.append(f"Global normalized similarity: {global_sim:.4f}")
    report.append(f"Rows: {len(rows)}")
    report.append(f"Rows similarity < 0.80: {len(low)}")
    report.append(f"Rows similarity < 0.50: {len(very_low)}")
    report.append("")
    report.append("Lowest similarity rows:")
    for r in sorted(rows, key=lambda x: float(x["similarity"]))[:30]:
        report.append(
            f"  row={r['row']} manual_break={r['manual_break']} manual_printed_page={r['manual_printed_page']} "
            f"v54_page={r['v54_page']} v54_img={r['v54_image']} sim={r['similarity']} "
            f"manual_chars={r['manual_chars']} v54_chars={r['v54_chars']}"
        )
    report.append("")
    report.append("Created:")
    report.append(f"  {out_dir / ('manual_docx_from_break_' + str(args.manual_break_start) + '.txt')}")
    report.append(f"  {out_dir / ('v54_from_page_' + str(args.v54_start_page) + '.txt')}")
    report.append(f"  {out_dir / 'comparison_report.txt'}")
    report.append(f"  {out_dir / 'page_comparison.csv'}")
    report.append(f"  {out_dir / 'diff_sample.txt'}")

    write_txt(out_dir / "comparison_report.txt", "\n".join(report) + "\n")

    print("Created:", out_dir / "comparison_report.txt")
    print("Created:", out_dir / "page_comparison.csv")
    print("Created:", out_dir / "diff_sample.txt")
    print("")
    print("Manual first non-empty line:", first_nonempty_line(manual_part))
    print(f"Global normalized similarity: {global_sim:.4f}")
    print(f"Rows similarity < 0.80: {len(low)}")
    print(f"Rows similarity < 0.50: {len(very_low)}")

if __name__ == "__main__":
    main()
