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
    docx_path = Path(docx_path)
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
                parts.append("\n")
            elif tag == "lastRenderedPageBreak":
                parts.append("\n<<<DOCX_PAGE_BREAK>>>\n")
        out.append("".join(parts))

    text = "\n".join(out)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text

def find_markers(text):
    result = []
    for m in PAGE_RE.finditer(text):
        p = m.group("page")
        result.append({
            "start": m.start(),
            "end": m.end(),
            "page_raw": p,
            "page_num": int(p) if p.isdigit() else None,
            "image": m.group("img").strip(),
            "header": m.group(0),
        })
    return result

def extract_from_page_marker(text, start_page):
    markers = find_markers(text)
    for m in markers:
        if m["page_num"] is not None and m["page_num"] >= start_page:
            return text[m["start"]:], "page_marker", str(m["page_num"])
    return "", "no_marker", ""

def extract_from_docx_breaks(text, start_page):
    pages = text.split("<<<DOCX_PAGE_BREAK>>>")
    if len(pages) >= start_page:
        return "<<<DOCX_PAGE_BREAK>>>".join(pages[start_page - 1:]), "docx_page_break", str(start_page)
    return "", "no_docx_break", ""

def extract_from_page(text, start_page):
    a, mode, found = extract_from_page_marker(text, start_page)
    if a:
        return a, mode, found
    return extract_from_docx_breaks(text, start_page)

def norm(text):
    text = PAGE_RE.sub(" ", text)
    text = text.replace("<<<DOCX_PAGE_BREAK>>>", " ")
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

def segments(text):
    markers = find_markers(text)
    if not markers:
        return []

    out = []
    for i, m in enumerate(markers):
        start = m["start"]
        end = markers[i + 1]["start"] if i + 1 < len(markers) else len(text)
        out.append({
            "page": m["page_raw"],
            "image": m["image"],
            "text": text[start:end],
        })
    return out

def write_page_csv(path, manual_text, v54_text):
    mseg = segments(manual_text)
    vseg = segments(v54_text)

    rows = []
    max_len = max(len(mseg), len(vseg))

    if max_len == 0:
        sim = difflib.SequenceMatcher(None, norm(manual_text), norm(v54_text)).ratio()
        rows.append({
            "page": "",
            "manual_image": "",
            "v54_image": "",
            "manual_chars": len(manual_text),
            "v54_chars": len(v54_text),
            "similarity": f"{sim:.4f}",
            "note": "no page markers",
        })
    else:
        for i in range(max_len):
            mt = mseg[i]["text"] if i < len(mseg) else ""
            vt = vseg[i]["text"] if i < len(vseg) else ""
            sim = difflib.SequenceMatcher(None, norm(mt), norm(vt)).ratio()
            rows.append({
                "page": mseg[i]["page"] if i < len(mseg) else vseg[i]["page"],
                "manual_image": mseg[i]["image"] if i < len(mseg) else "",
                "v54_image": vseg[i]["image"] if i < len(vseg) else "",
                "manual_chars": len(mt),
                "v54_chars": len(vt),
                "similarity": f"{sim:.4f}",
                "note": "",
            })

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "page",
                "manual_image",
                "v54_image",
                "manual_chars",
                "v54_chars",
                "similarity",
                "note",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)

    return rows

def make_diff(path, manual_text, v54_text, limit=12000):
    diff = difflib.unified_diff(
        manual_text.splitlines(),
        v54_text.splitlines(),
        fromfile="DOCX_from_page",
        tofile="V54_from_page",
        lineterm="",
        n=3,
    )

    lines = []
    for i, line in enumerate(diff):
        if i >= limit:
            lines.append("... diff truncated ...")
            break
        lines.append(line)

    write_txt(path, "\n".join(lines))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manual-docx", required=True)
    ap.add_argument("--v54-final", required=True)
    ap.add_argument("--start-page", type=int, default=73)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("Reading DOCX...")
    docx_all = extract_docx_text(args.manual_docx)

    print("Reading v5.4 final...")
    v54_all = read_txt(args.v54_final)

    docx_part, docx_mode, docx_found = extract_from_page(docx_all, args.start_page)
    v54_part, v54_mode, v54_found = extract_from_page(v54_all, args.start_page)

    if not docx_part:
        raise SystemExit("Could not extract DOCX from requested page.")
    if not v54_part:
        raise SystemExit("Could not extract v54 from requested page.")

    write_txt(out_dir / f"manual_docx_from_page_{args.start_page}.txt", docx_part)
    write_txt(out_dir / f"v54_from_page_{args.start_page}.txt", v54_part)

    rows = write_page_csv(out_dir / "page_comparison.csv", docx_part, v54_part)
    make_diff(out_dir / "diff_sample.txt", docx_part, v54_part)

    global_sim = difflib.SequenceMatcher(None, norm(docx_part), norm(v54_part)).ratio()

    low = [r for r in rows if float(r["similarity"]) < 0.80]
    very_low = [r for r in rows if float(r["similarity"]) < 0.50]

    report = []
    report.append("compare_docx_from_page_with_v54.py report")
    report.append("")
    report.append(f"Manual DOCX: {args.manual_docx}")
    report.append(f"V5.4 final TXT: {args.v54_final}")
    report.append(f"Start page: {args.start_page}")
    report.append("")
    report.append("Extraction:")
    report.append(f"  manual mode: {docx_mode}")
    report.append(f"  manual first found: {docx_found}")
    report.append(f"  v54 mode: {v54_mode}")
    report.append(f"  v54 first found: {v54_found}")
    report.append("")
    report.append("Manual DOCX stats:")
    for k, v in stats(docx_part).items():
        report.append(f"  {k}: {v}")
    report.append("")
    report.append("V5.4 stats:")
    for k, v in stats(v54_part).items():
        report.append(f"  {k}: {v}")
    report.append("")
    report.append(f"Global normalized similarity: {global_sim:.4f}")
    report.append(f"Page rows: {len(rows)}")
    report.append(f"Rows similarity < 0.80: {len(low)}")
    report.append(f"Rows similarity < 0.50: {len(very_low)}")
    report.append("")
    report.append("Lowest similarity rows:")
    for r in sorted(rows, key=lambda x: float(x["similarity"]))[:30]:
        report.append(
            f"  page={r['page']} sim={r['similarity']} "
            f"manual_img={r['manual_image']} v54_img={r['v54_image']} "
            f"manual_chars={r['manual_chars']} v54_chars={r['v54_chars']}"
        )
    report.append("")
    report.append("Created:")
    report.append(f"  {out_dir / ('manual_docx_from_page_' + str(args.start_page) + '.txt')}")
    report.append(f"  {out_dir / ('v54_from_page_' + str(args.start_page) + '.txt')}")
    report.append(f"  {out_dir / 'comparison_report.txt'}")
    report.append(f"  {out_dir / 'page_comparison.csv'}")
    report.append(f"  {out_dir / 'diff_sample.txt'}")

    write_txt(out_dir / "comparison_report.txt", "\n".join(report) + "\n")

    print("Created:", out_dir / "comparison_report.txt")
    print("Created:", out_dir / "page_comparison.csv")
    print("Created:", out_dir / "diff_sample.txt")
    print("")
    print(f"Global normalized similarity: {global_sim:.4f}")
    print(f"Rows similarity < 0.80: {len(low)}")
    print(f"Rows similarity < 0.50: {len(very_low)}")

if __name__ == "__main__":
    main()