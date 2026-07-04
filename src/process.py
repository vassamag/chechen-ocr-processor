import argparse
import re
from pathlib import Path

import pytesseract
from PIL import Image
from docx import Document
from docx.enum.text import WD_COLOR_INDEX


# ============================================================
# Chechen OCR Post-Correction Processor
# process.py v5.3.2
#
# Pipeline:
# image -> Tesseract OCR -> Chechen OCR post-correction
#       -> TXT/DOCX + correction/suspicious reports
# ============================================================


# Path to Tesseract on your Windows machine.
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"


CORRECTION_LOG = []
SUSPICIOUS_LOG = []


# Characters often confused with Chechen palochka Ӏ.
PALOCHKA_CHARS = "Iil1|![]ЇїІіЈј"


# Words/names that should not be marked suspicious.
SUSPICIOUS_WHITELIST = {
    "Маьлха-Аьзни",
    "Маьлха-Аьзнис",
    "Тату-Хепас",
    "Тату-Хепин",
    "JPG-файлов",
}


# Known suspicious OCR patterns where we know a likely correction,
# but do not want to auto-correct without human validation.
KNOWN_SUSPICIOUS_CANDIDATES = {
    "Аълбикин": ["Аьлбикин"],
    "Маьлха-Аъзнис": ["Маьлха-Аьзнис"],
    "бТарлаех": ["бӀарлаех"],
    "ДиЙЦинчо": ["Дийцинчо"],
    "ЮьхыШаьржа": ["ЮьхьӀаьржа"],
    "юьхыШаьржа": ["юьхьӀаьржа"],
}


# Loaded from rules/palochka_words.txt
PALOCHKA_DICTIONARY = set()


def log_correction(kind: str, before: str, after: str) -> None:
    if before != after:
        CORRECTION_LOG.append(f"{kind}: {before} -> {after}")


def clean_ocr_artifacts(text: str) -> str:
    """
    Light cleanup of OCR artifacts without changing language content too aggressively.
    """
    # Normalize line endings.
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # Remove excessive spaces/tabs.
    text = re.sub(r"[ \t]+", " ", text)

    # Remove spaces before punctuation.
    text = re.sub(r"\s+([,.!?;:])", r"\1", text)

    # Normalize some repeated blank lines but keep paragraph structure.
    text = re.sub(r"\n{4,}", "\n\n\n", text)

    return text.strip() + "\n"


def normalize_palochka(text: str) -> str:
    """
    Normalizes direct palochka lookalikes and common OCR palochka patterns.

    Direct:
    І, і, ӏ -> Ӏ

    Pattern:
    г!, к1, т[, х|, etc. -> гӀ, кӀ, тӀ, хӀ
    """
    direct_replacements = {
        "І": "Ӏ",
        "і": "Ӏ",
        "ӏ": "Ӏ",
    }

    for before, after in direct_replacements.items():
        count = text.count(before)
        if count:
            text = text.replace(before, after)
            for _ in range(count):
                log_correction("palochka_direct", before, after)

    # Base Chechen consonants that often take palochka.
    base_letters = "гкптхцчдбГКПТХЦЧДБ"

    # Lookalikes after base letters.
    lookalikes = "Iil1|![]ЇїЈј"

    pattern = re.compile(f"([{base_letters}])([{re.escape(lookalikes)}])")

    def repl(match):
        before = match.group(0)
        after = match.group(1) + "Ӏ"
        log_correction("palochka_pattern", before, after)
        return after

    text = pattern.sub(repl, text)

    return text


def fix_common_chechen_ocr_words(text: str) -> str:
    """
    Conservative direct replacements for common OCR mistakes.

    This layer should contain only highly safe replacements.
    """
    replacements = {
        # Common h/palochka words
        "хТара": "хӀара",
        "хТун": "хӀун",
        "хГун": "хӀун",
        "хГума": "хӀума",
        "хГуманаш": "хӀуманаш",
        "хГумано": "хӀумано",
        "хГуманан": "хӀуманан",
        "хГуманна": "хӀуманна",
        "хГумма": "хӀумма",
        "хТокху": "хӀокху",
        "хГокху": "хӀокху",
        "хТокхуьнгахь": "хӀокхуьнгахь",
        "хГокхуьнгахь": "хӀокхуьнгахь",
        "хТинца": "хӀинца",
        "хТинццалц": "хӀинццалц",
        "хТиттийна": "хӀиттийна",
        "хТоттийначу": "хӀоттийначу",
        "хГоттийначу": "хӀоттийначу",
        "хГусам": "хӀусам",
        "хГусаман": "хӀусаман",
        "хГусамаш": "хӀусамаш",
        "хГусамийн": "хӀусамийн",
        "хГусамнана": "хӀусамнана",
        "ХГусаман": "ХӀусаман",
        "ХТокху": "ХӀокху",
        "ХГокху": "ХӀокху",
        "ХТокхуьнгахь": "ХӀокхуьнгахь",
        "ХГокхуьнгахь": "ХӀокхуьнгахь",
        "ХТетахь": "ХӀетахь",
        "ХГара": "ХӀара",

        # k/palochka
        "кТант": "кӀант",
        "КТант": "КӀант",
        "КТантана": "КӀантана",
        "кТантана": "кӀантана",
        "кТеда": "кӀеда",
        "кТайн": "кӀайн",
        "КТайн": "КӀайн",
        "кТентан": "кӀентан",
        "КТентан": "КӀентан",

        # b/palochka
        "бТаьрг": "бӀаьрг",
        "бТаьргаша": "бӀаьргаша",
        "бТаьргийн": "бӀаьргийн",
        "бТаьргаш": "бӀаьргаш",
        "бТе": "бӀе",

        # d/palochka
        "дГаала": "дӀаала",
        "дГабуза": "дӀабуза",
        "дТабуза": "дӀабуза",
        "дТадала": "дӀадала",
        "дТало": "дӀало",
        "дТасадаьржинчу": "дӀасадаьржинчу",

        # g/palochka
        "гТурбанна": "гӀурбанна",
        "гГурбанна": "гӀурбанна",
        "гТорасиз": "гӀорасиз",
        "гГорасиз": "гӀорасиз",
        "гГовгТа": "гӀовгӀа",

        # yo/palochka
        "йо]": "йоӀ",
        "йо!": "йоӀ",
        "йо1": "йоӀ",
        "Йо]": "ЙоӀ",
        "Йо!": "ЙоӀ",
        "Йо1": "ЙоӀ",

        # Other known direct forms
        "[або": "Ӏабо",
        "до[учу": "доӀучу",
        "до]анна": "доӀанна",
        "не!арш": "неӀарш",
        "секха[ад": "секхаӀад",
        "та]ийра": "таӀийра",
        "та[зарна": "таӀзарна",
        "та!ийна": "таӀийна",
        "вогТура": "вогӀура",
        "чТуг": "чӀуг",
        "мухТар": "мухӀар",
        "дегТахь": "дегӀахь",
    }

    # Longer keys first to avoid partial replacement issues.
    for before in sorted(replacements.keys(), key=len, reverse=True):
        after = replacements[before]
        if before in text:
            count = text.count(before)
            text = text.replace(before, after)
            for _ in range(count):
                log_correction("dictionary", before, after)

    return text


def load_palochka_words() -> set[str]:
    """
    Loads dictionary of Chechen words containing Ӏ.
    Expected file:
    rules/palochka_words.txt
    """
    path = Path("rules") / "palochka_words.txt"

    if not path.exists():
        return set()

    words = set()

    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            word = line.strip()
            if word:
                words.add(word.lower())

    return words


def split_token(token: str) -> tuple[str, str, str]:
    """
    Splits token into prefix punctuation, core word, suffix punctuation.
    """
    match = re.match(r"^([^А-Яа-яЁёӀA-Za-z0-9]*)(.*?)([^А-Яа-яЁёӀA-Za-z0-9]*)$", token)
    if not match:
        return "", token, ""

    return match.group(1), match.group(2), match.group(3)


def preserve_case(original: str, candidate: str) -> str:
    """
    Preserve simple capitalization style.
    """
    if not original:
        return candidate

    if original.isupper():
        return candidate.upper()

    if original[0].isupper():
        return candidate[:1].upper() + candidate[1:]

    return candidate


def generate_palochka_candidates(word: str) -> set[str]:
    """
    Generates possible corrections by replacing OCR lookalikes/pairs with Ӏ.
    """
    candidates = set()

    if not word:
        return candidates

    lower_word = word.lower()

    # Single-character replacements.
    lookalikes = {
        "I": "Ӏ",
        "i": "Ӏ",
        "l": "Ӏ",
        "1": "Ӏ",
        "|": "Ӏ",
        "!": "Ӏ",
        "[": "Ӏ",
        "]": "Ӏ",
        "І": "Ӏ",
        "і": "Ӏ",
        "Ї": "Ӏ",
        "ї": "Ӏ",
        "Ј": "Ӏ",
        "ј": "Ӏ",
    }

    for bad, good in lookalikes.items():
        if bad in word:
            candidates.add(word.replace(bad, good))
            candidates.add(lower_word.replace(bad.lower(), good))

    # Pair replacements where the second character is likely OCR damage for Ӏ.
        pair_replacements = {
        # к + OCR-palochka damage -> кӀ
        "кт": "кӀ",
        "кТ": "кӀ",
        "КТ": "КӀ",
        "кг": "кӀ",
        "кГ": "кӀ",
        "КГ": "КӀ",

        # х + OCR-palochka damage -> хӀ
        "хг": "хӀ",
        "хГ": "хӀ",
        "ХГ": "ХӀ",
        "хт": "хӀ",
        "хТ": "хӀ",
        "ХТ": "ХӀ",

        # д + OCR-palochka damage -> дӀ
        "дг": "дӀ",
        "дГ": "дӀ",
        "ДГ": "ДӀ",
        "дт": "дӀ",
        "дТ": "дӀ",
        "ДТ": "ДӀ",

        # б + OCR-palochka damage -> бӀ
        "бт": "бӀ",
        "бТ": "бӀ",
        "БТ": "БӀ",
        "бг": "бӀ",
        "бГ": "бӀ",
        "БГ": "БӀ",

        # г + OCR-palochka damage -> гӀ
        "гт": "гӀ",
        "гТ": "гӀ",
        "ГТ": "ГӀ",
        
        # т + OCR-palochka damage -> тӀ
        "тг": "тӀ",
        "тГ": "тӀ",
        "ТГ": "ТӀ",

        # п + OCR-palochka damage -> пӀ
        "пг": "пӀ",
        "пГ": "пӀ",
        "ПГ": "ПӀ",

        # ц / ч + OCR-palochka damage -> цӀ / чӀ
        "цт": "цӀ",
        "цТ": "цӀ",
        "ЦТ": "ЦӀ",
        "чт": "чӀ",
        "чТ": "чӀ",
        "ЧТ": "ЧӀ",

        # йо + OCR-palochka damage -> йоӀ
        "йот": "йоӀ",
        "йоТ": "йоӀ",
        "ЙоТ": "ЙоӀ",
    }

    for before, after in pair_replacements.items():
        if before in word:
            candidates.add(word.replace(before, after))

    return candidates


def fix_words_using_palochka_dictionary(text: str) -> str:
    """
    Auto-corrects only if exactly one generated palochka candidate exists
    in the dictionary.
    """
    if not PALOCHKA_DICTIONARY:
        return text

    def repl(match):
        token = match.group(0)
        prefix, core, suffix = split_token(token)

        if not core:
            return token

        # Protect pure numbers.
        if core.isdigit():
            return token

        # Do not alter words already valid in dictionary.
        if core.lower() in PALOCHKA_DICTIONARY:
            return token

        candidates = generate_palochka_candidates(core)

        valid = []
        for cand in candidates:
            if cand.lower() in PALOCHKA_DICTIONARY:
                valid.append(cand)

        unique_valid = sorted(set(valid), key=len)

        if len(unique_valid) == 1:
            corrected_core = preserve_case(core, unique_valid[0])
            corrected = prefix + corrected_core + suffix
            log_correction("dictionary", core, corrected_core)
            return corrected

        return token

    # Words/tokens that may include OCR symbols.
    token_pattern = re.compile(r"[А-Яа-яЁёӀA-Za-z0-9ІіЇїЈј\[\]\|!]+", flags=re.UNICODE)
    return token_pattern.sub(repl, text)


def normalize_internal_uppercase_candidate(word: str) -> str | None:
    """
    Candidate for words with internal uppercase letters:
    ДиЙЦинчо -> Дийцинчо

    Does not treat Ӏ as suspicious uppercase.
    Preserves uppercase after hyphen.
    """
    if not word:
        return None

    chars = list(word)
    changed = False

    for i, ch in enumerate(chars):
        if ch == "Ӏ":
            continue

        if i == 0:
            continue

        if i > 0 and chars[i - 1] == "-":
            continue

        if ch.isupper():
            chars[i] = ch.lower()
            changed = True

    if not changed:
        return None

    candidate = "".join(chars)

    if candidate == word:
        return None

    return candidate


def is_whitelisted_word(word: str) -> bool:
    clean = word.strip(".,!?;:()[]{}«»\"'“”„")
    return clean in SUSPICIOUS_WHITELIST


def is_mixed_case_inside_word(word: str) -> bool:
    """
    True if word has unexpected uppercase letters inside.
    Ignores:
    - first letter
    - Ӏ
    - uppercase after hyphen
    - all-uppercase words
    """
    if len(word) < 2:
        return False

    if word.isupper():
        return False

    for i, ch in enumerate(word):
        if ch == "Ӏ":
            continue

        if i == 0:
            continue

        if i > 0 and word[i - 1] == "-":
            continue

        if ch.isupper():
            return True

    return False


def get_suspicious_candidates(word: str) -> list[str]:
    """
    Returns possible candidates for suspicious word.
    These are suggestions only, not auto-corrections.
    """
    clean_word = word.strip(".,!?;:()[]{}«»\"'“”„")

    if not clean_word:
        return []

    if clean_word in KNOWN_SUSPICIOUS_CANDIDATES:
        return KNOWN_SUSPICIOUS_CANDIDATES[clean_word]

    candidates = []

    for cand in generate_palochka_candidates(clean_word):
        if cand.lower() in PALOCHKA_DICTIONARY:
            candidates.append(cand)

    lowercase_candidate = normalize_internal_uppercase_candidate(clean_word)
    if lowercase_candidate:
        candidates.append(lowercase_candidate)

    # Unique, stable order.
    result = []
    seen = set()

    for cand in candidates:
        if cand not in seen:
            result.append(cand)
            seen.add(cand)

    return result


def is_suspicious_word(word: str) -> tuple[bool, str]:
    """
    Determines whether a word looks suspicious after OCR.
    Returns:
    (True/False, reason)
    """
    if len(word) < 2:
        return False, ""

    clean_word = word.strip(".,!?;:()[]{}«»\"'“”„")

    if not clean_word:
        return False, ""

    # Do not mark pure numbers as suspicious.
    # Examples: 11, 111, 273.
    if clean_word.isdigit():
        return False, ""

    if is_whitelisted_word(clean_word):
        return False, ""

    # If word is already valid in palochka dictionary, do not highlight it.
    if clean_word.lower() in PALOCHKA_DICTIONARY:
        return False, ""

    # Known suspicious OCR patterns.
    if clean_word in KNOWN_SUSPICIOUS_CANDIDATES:
        return True, "known OCR pattern"

    suspicious_chars = ["[", "]", "|", "1"]

    for ch in suspicious_chars:
        if ch in clean_word:
            return True, f"contains suspicious OCR char '{ch}'"

    # ! is suspicious only inside a word, not as final punctuation.
    if "!" in clean_word[:-1]:
        return True, "contains suspicious OCR char '!' inside word"

    # Mixed Latin/Cyrillic inside one word.
    if re.search(r"[A-Za-z]", clean_word) and re.search(r"[А-Яа-яЁёӀ]", clean_word):
        return True, "mixed Latin/Cyrillic characters"

    # Suspicious OCR combinations around possible palochka.
    suspicious_pairs = [
        "хГ", "ХГ",
        "хТ", "ХТ",
        "дГ", "ДГ",
        "дТ", "ДТ",
        "бТ", "БТ",
        "КТ", "кт",
        "ГТ", "гт",
        "йоТ", "ЙоТ",
        "хХ", "ХХ",
    ]

    for pair in suspicious_pairs:
        if pair in clean_word:
            return True, f"suspicious pair '{pair}'"

    if is_mixed_case_inside_word(clean_word):
        return True, "uppercase letter inside word"

    return False, ""


def detect_suspicious_words(text: str) -> list[str]:
    """
    Detects suspicious words and writes SUSPICIOUS_LOG.
    Returns list of suspicious words.
    """
    SUSPICIOUS_LOG.clear()

    words = re.findall(r"[А-Яа-яЁёӀA-Za-z0-9ІіЇїЈј\[\]\|!\-]+", text, flags=re.UNICODE)

    suspicious = []

    for word in words:
        is_bad, reason = is_suspicious_word(word)

        if not is_bad:
            continue

        candidates = get_suspicious_candidates(word)
        candidates_text = ", ".join(candidates) if candidates else "none"

        clean_word = word.strip(".,!?;:()[]{}«»\"'“”„")

        SUSPICIOUS_LOG.append(
            f"{clean_word} | reason: {reason} | candidates: {candidates_text}"
        )
        suspicious.append(clean_word)

    # Deduplicate while preserving order.
    seen = set()
    unique = []

    unique_log = []
    seen_log = set()

    for item in suspicious:
        if item not in seen:
            unique.append(item)
            seen.add(item)

    for line in SUSPICIOUS_LOG:
        if line not in seen_log:
            unique_log.append(line)
            seen_log.add(line)

    SUSPICIOUS_LOG.clear()
    SUSPICIOUS_LOG.extend(unique_log)

    return unique


def post_correct_chechen_ocr(text: str) -> str:
    """
    Main post-correction function.
    """
    text = clean_ocr_artifacts(text)
    text = normalize_palochka(text)
    text = fix_common_chechen_ocr_words(text)
    text = fix_words_using_palochka_dictionary(text)
    text = clean_ocr_artifacts(text)
    return text


def ocr_image(image_path: Path, lang: str = "rus") -> str:
    """
    Runs Tesseract OCR on image.
    """
    image = Image.open(image_path)
    text = pytesseract.image_to_string(image, lang=lang)
    return text


def save_txt(text: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def add_text_with_highlights(document: Document, text: str, suspicious_words: set[str]) -> None:
    """
    Adds text to DOCX and highlights suspicious words.
    """
    token_pattern = re.compile(r"([А-Яа-яЁёӀA-Za-z0-9ІіЇїЈј\[\]\|!\-]+|\s+|.)", flags=re.UNICODE)

    for paragraph_text in text.split("\n"):
        paragraph = document.add_paragraph()

        for token in token_pattern.findall(paragraph_text):
            run = paragraph.add_run(token)

            clean = token.strip(".,!?;:()[]{}«»\"'“”„")

            if clean in suspicious_words:
                run.font.highlight_color = WD_COLOR_INDEX.YELLOW


def save_docx(text: str, path: Path, suspicious_words: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    document = Document()

    if suspicious_words:
        add_text_with_highlights(document, text, set(suspicious_words))
    else:
        for paragraph_text in text.split("\n"):
            document.add_paragraph(paragraph_text)

    document.save(path)


def save_correction_report(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    if CORRECTION_LOG:
        text = "\n".join(CORRECTION_LOG) + "\n"
    else:
        text = "No corrections.\n"

    path.write_text(text, encoding="utf-8")


def save_suspicious_report(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    if SUSPICIOUS_LOG:
        text = "\n".join(SUSPICIOUS_LOG) + "\n"
    else:
        text = "No suspicious words.\n"

    path.write_text(text, encoding="utf-8")


def process_image(input_path: Path, output_path: Path, lang: str = "rus") -> None:
    """
    Processes one image.
    """
    global PALOCHKA_DICTIONARY

    CORRECTION_LOG.clear()
    SUSPICIOUS_LOG.clear()

    PALOCHKA_DICTIONARY = load_palochka_words()

    input_path = Path(input_path)
    output_path = Path(output_path)

    if not input_path.exists():
        raise FileNotFoundError(f"Input image not found: {input_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"OCR image: {input_path}")

    raw_text = ocr_image(input_path, lang=lang)
    corrected_text = post_correct_chechen_ocr(raw_text)
    suspicious_words = detect_suspicious_words(corrected_text)

    raw_txt_path = output_path.with_name(output_path.stem + "_raw_ocr.txt")
    corrected_txt_path = output_path.with_suffix(".txt")
    correction_report_path = output_path.with_name(output_path.stem + "_corrections.txt")
    suspicious_report_path = output_path.with_name(output_path.stem + "_suspicious.txt")

    save_txt(raw_text, raw_txt_path)
    print(f"Raw OCR saved: {raw_txt_path}")

    save_txt(corrected_text, corrected_txt_path)
    print(f"Corrected TXT saved: {corrected_txt_path}")

    save_docx(corrected_text, output_path, suspicious_words)
    print(f"Corrected DOCX saved: {output_path}")

    save_correction_report(correction_report_path)
    print(f"Correction report saved: {correction_report_path}")

    save_suspicious_report(suspicious_report_path)
    print(f"Suspicious report saved: {suspicious_report_path}")

    print(f"Suspicious words highlighted: {len(suspicious_words)}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Chechen OCR post-correction processor"
    )

    parser.add_argument(
        "input",
        help="Input image path"
    )

    parser.add_argument(
        "--output",
        default="output/result.docx",
        help="Output DOCX path"
    )

    parser.add_argument(
        "--lang",
        default="rus",
        help="Tesseract language, default: rus"
    )

    args = parser.parse_args()

    process_image(
        input_path=Path(args.input),
        output_path=Path(args.output),
        lang=args.lang,
    )


if __name__ == "__main__":
    main()