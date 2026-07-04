import argparse
import re
from collections import Counter, defaultdict
from pathlib import Path


VERSION = "v1.0"


def read_lines(path: Path) -> list[str]:
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    return path.read_text(encoding="utf-8", errors="replace").splitlines()


def parse_correction_line(line: str):
    """
    Example:
    dictionary: хТинца -> хӀинца

    Returns:
    kind, before, after
    """
    if ":" not in line or "->" not in line:
        return None

    kind_part, rest = line.split(":", 1)
    before_after = rest.split("->", 1)

    if len(before_after) != 2:
        return None

    kind = kind_part.strip()
    before = before_after[0].strip()
    after = before_after[1].strip()

    if not kind or not before or not after:
        return None

    return kind, before, after


def parse_suspicious_line(line: str):
    """
    Example:
    бТоболуьйтург | reason: suspicious pair 'бТ' | candidates: бтоболуьйтург

    Returns:
    word, reason, candidates
    """
    parts = [part.strip() for part in line.split("|")]

    if len(parts) < 2:
        return None

    word = parts[0].strip()

    reason = ""
    candidates = ""

    for part in parts[1:]:
        if part.startswith("reason:"):
            reason = part.replace("reason:", "", 1).strip()
        elif part.startswith("candidates:"):
            candidates = part.replace("candidates:", "", 1).strip()

    if not word or not reason:
        return None

    return word, reason, candidates


def write_counter(path: Path, title: str, counter: Counter, limit: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    lines = [title, "=" * len(title), ""]

    items = counter.most_common(limit)

    for key, count in items:
        lines.append(f"{count}\t{key}")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def analyze_corrections(correction_lines: list[str], output_dir: Path) -> None:
    parsed = []

    for line in correction_lines:
        item = parse_correction_line(line)
        if item:
            parsed.append(item)

    kind_counter = Counter()
    pair_counter = Counter()
    before_counter = Counter()
    after_counter = Counter()

    for kind, before, after in parsed:
        kind_counter[kind] += 1
        pair_counter[f"{before} -> {after}"] += 1
        before_counter[before] += 1
        after_counter[after] += 1

    summary_lines = [
        f"Correction analysis {VERSION}",
        "=" * 40,
        "",
        f"Total correction lines: {len(correction_lines)}",
        f"Parsed correction lines: {len(parsed)}",
        "",
        "By correction type:",
    ]

    for kind, count in kind_counter.most_common():
        summary_lines.append(f"{count}\t{kind}")

    summary_lines.extend([
        "",
        "Top correction pairs:",
    ])

    for pair, count in pair_counter.most_common(100):
        summary_lines.append(f"{count}\t{pair}")

    (output_dir / "correction_summary.txt").write_text(
        "\n".join(summary_lines) + "\n",
        encoding="utf-8"
    )

    write_counter(
        output_dir / "correction_top_pairs.txt",
        "Top correction pairs",
        pair_counter,
        limit=300,
    )

    write_counter(
        output_dir / "correction_top_before.txt",
        "Top correction BEFORE tokens",
        before_counter,
        limit=300,
    )

    write_counter(
        output_dir / "correction_top_after.txt",
        "Top correction AFTER tokens",
        after_counter,
        limit=300,
    )


def extract_suspicious_pair(reason: str) -> str | None:
    """
    Extracts pair from:
    suspicious pair 'бТ'
    """
    match = re.search(r"suspicious pair '([^']+)'", reason)
    if match:
        return match.group(1)
    return None


def classify_word_shape(word: str) -> str:
    """
    Rough OCR-shape classification for suspicious words.
    """
    if "[" in word:
        return "contains_["
    if "]" in word:
        return "contains_]"
    if "|" in word:
        return "contains_|"
    if "!" in word:
        return "contains_!"
    if "1" in word:
        return "contains_1"

    if re.search(r"[A-Za-z]", word) and re.search(r"[А-Яа-яЁёӀ]", word):
        return "mixed_latin_cyrillic"

    if re.search(r"[А-ЯЁ][А-ЯЁ]", word):
        return "double_uppercase"

    if re.search(r"[а-яё][А-ЯЁ]", word):
        return "internal_uppercase"

    return "other"


def get_internal_uppercase_patterns(word: str) -> list[str]:
    """
    Finds local patterns around internal uppercase letters.

    Example:
    маьркТажан -> кТ
    ладоыТуш -> ыТ
    """
    patterns = []

    for i, ch in enumerate(word):
        if ch == "Ӏ":
            continue

        if not ch.isupper():
            continue

        if i == 0:
            continue

        if i > 0 and word[i - 1] == "-":
            continue

        left = word[i - 1] if i - 1 >= 0 else ""
        right = word[i + 1] if i + 1 < len(word) else ""

        if left:
            patterns.append(left + ch)

        if right:
            patterns.append(ch + right)

        if left and right:
            patterns.append(left + ch + right)

    return patterns


def analyze_suspicious(suspicious_lines: list[str], output_dir: Path) -> None:
    parsed = []

    for line in suspicious_lines:
        item = parse_suspicious_line(line)
        if item:
            parsed.append(item)

    reason_counter = Counter()
    word_counter = Counter()
    candidate_counter = Counter()
    shape_counter = Counter()
    suspicious_pair_counter = Counter()
    internal_uppercase_pattern_counter = Counter()
    first_char_counter = Counter()

    words_by_reason = defaultdict(list)

    for word, reason, candidates in parsed:
        reason_counter[reason] += 1
        word_counter[word] += 1
        shape_counter[classify_word_shape(word)] += 1
        first_char_counter[word[:1]] += 1
        words_by_reason[reason].append((word, candidates))

        if candidates and candidates != "none":
            candidate_counter[candidates] += 1

        pair = extract_suspicious_pair(reason)
        if pair:
            suspicious_pair_counter[pair] += 1

        if reason == "uppercase letter inside word":
            for pattern in get_internal_uppercase_patterns(word):
                internal_uppercase_pattern_counter[pattern] += 1

    summary_lines = [
        f"Suspicious analysis {VERSION}",
        "=" * 40,
        "",
        f"Total suspicious lines: {len(suspicious_lines)}",
        f"Parsed suspicious lines: {len(parsed)}",
        "",
        "By reason:",
    ]

    for reason, count in reason_counter.most_common():
        summary_lines.append(f"{count}\t{reason}")

    summary_lines.extend([
        "",
        "By word shape:",
    ])

    for shape, count in shape_counter.most_common():
        summary_lines.append(f"{count}\t{shape}")

    summary_lines.extend([
        "",
        "Suspicious pairs:",
    ])

    for pair, count in suspicious_pair_counter.most_common():
        summary_lines.append(f"{count}\t{pair}")

    summary_lines.extend([
        "",
        "Internal uppercase local patterns:",
    ])

    for pattern, count in internal_uppercase_pattern_counter.most_common(100):
        summary_lines.append(f"{count}\t{pattern}")

    (output_dir / "suspicious_summary.txt").write_text(
        "\n".join(summary_lines) + "\n",
        encoding="utf-8"
    )

    write_counter(
        output_dir / "suspicious_by_reason.txt",
        "Suspicious by reason",
        reason_counter,
        limit=None,
    )

    write_counter(
        output_dir / "suspicious_top_words.txt",
        "Suspicious top words",
        word_counter,
        limit=500,
    )

    write_counter(
        output_dir / "suspicious_top_candidates.txt",
        "Suspicious top candidates",
        candidate_counter,
        limit=500,
    )

    write_counter(
        output_dir / "suspicious_shapes.txt",
        "Suspicious word shapes",
        shape_counter,
        limit=None,
    )

    write_counter(
        output_dir / "suspicious_pairs.txt",
        "Suspicious pairs",
        suspicious_pair_counter,
        limit=None,
    )

    write_counter(
        output_dir / "suspicious_internal_uppercase_patterns.txt",
        "Internal uppercase local patterns",
        internal_uppercase_pattern_counter,
        limit=500,
    )

    # Detailed grouped report.
    grouped_lines = [
        "Suspicious grouped by reason",
        "=" * 40,
        "",
    ]

    for reason, items in sorted(
        words_by_reason.items(),
        key=lambda kv: len(kv[1]),
        reverse=True
    ):
        grouped_lines.append(f"## {reason} ({len(items)})")
        grouped_lines.append("")

        for word, candidates in items[:300]:
            grouped_lines.append(f"{word}\t candidates: {candidates}")

        grouped_lines.append("")

    (output_dir / "suspicious_grouped_by_reason.txt").write_text(
        "\n".join(grouped_lines) + "\n",
        encoding="utf-8"
    )

    # Candidate patterns for future rules.
    pattern_lines = [
        "Suspicious pattern candidates for future processor rules",
        "=" * 60,
        "",
        "1) Frequent suspicious pairs",
        "",
    ]

    for pair, count in suspicious_pair_counter.most_common():
        pattern_lines.append(f"{count}\t{pair}")

    pattern_lines.extend([
        "",
        "2) Frequent internal uppercase local patterns",
        "",
    ])

    for pattern, count in internal_uppercase_pattern_counter.most_common(200):
        pattern_lines.append(f"{count}\t{pattern}")

    pattern_lines.extend([
        "",
        "3) Frequent words needing human review",
        "",
    ])

    for word, count in word_counter.most_common(300):
        pattern_lines.append(f"{count}\t{word}")

    (output_dir / "suspicious_pattern_candidates.txt").write_text(
        "\n".join(pattern_lines) + "\n",
        encoding="utf-8"
    )


def main():
    parser = argparse.ArgumentParser(
        description="Analyze Chechen OCR correction and suspicious reports"
    )

    parser.add_argument(
        "--corrections",
        required=True,
        help="Path to *_corrections.txt"
    )

    parser.add_argument(
        "--suspicious",
        required=True,
        help="Path to *_suspicious.txt"
    )

    parser.add_argument(
        "--output-dir",
        default="output/analysis",
        help="Directory for analysis reports"
    )

    args = parser.parse_args()

    corrections_path = Path(args.corrections)
    suspicious_path = Path(args.suspicious)
    output_dir = Path(args.output_dir)

    output_dir.mkdir(parents=True, exist_ok=True)

    correction_lines = read_lines(corrections_path)
    suspicious_lines = read_lines(suspicious_path)

    analyze_corrections(correction_lines, output_dir)
    analyze_suspicious(suspicious_lines, output_dir)

    print(f"analyze_reports.py version: {VERSION}")
    print(f"Corrections file: {corrections_path}")
    print(f"Suspicious file: {suspicious_path}")
    print(f"Output dir: {output_dir}")
    print("Done.")


if __name__ == "__main__":
    main()