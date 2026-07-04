import re
from pathlib import Path
from datasets import load_dataset


DATASET_NAME = "NM-development/nmd-ce-ru-171k-v0"

PROJECT_DIR = Path(__file__).resolve().parent
RULES_DIR = PROJECT_DIR / "rules"

PHRASES_FILE = RULES_DIR / "chechen_phrases.txt"
WORDS_FILE = RULES_DIR / "chechen_words.txt"
PALOCHKA_WORDS_FILE = RULES_DIR / "palochka_words.txt"

# Чеченская/русская кириллица + чеченская палочка Ӏ
WORD_RE = re.compile(r"[А-Яа-яЁёӀ]+(?:[-’'][А-Яа-яЁёӀ]+)*")


def normalize_text(text: str) -> str:
    text = str(text)
    text = text.replace("І", "Ӏ")
    text = text.replace("і", "Ӏ")
    text = text.replace("I", "Ӏ")
    text = text.replace("ӏ", "Ӏ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def main():
    RULES_DIR.mkdir(exist_ok=True)

    print(f"Downloading/loading dataset: {DATASET_NAME}")
    dataset = load_dataset(DATASET_NAME)

    phrases = set()
    words = set()
    palochka_words = set()

    total_rows = 0

    for split_name, split_data in dataset.items():
        print(f"Processing split: {split_name}, rows: {len(split_data)}")

        for row in split_data:
            total_rows += 1
            ce_text = row.get("ce", "")
            ce_text = normalize_text(ce_text)

            if not ce_text:
                continue

            phrases.add(ce_text)

            for word in WORD_RE.findall(ce_text):
                word = normalize_text(word)
                if len(word) < 2:
                    continue

                words.add(word)

                if "Ӏ" in word:
                    palochka_words.add(word)

    phrases_sorted = sorted(phrases)
    words_sorted = sorted(words, key=lambda x: (x.lower(), x))
    palochka_words_sorted = sorted(palochka_words, key=lambda x: (x.lower(), x))

    PHRASES_FILE.write_text("\n".join(phrases_sorted), encoding="utf-8")
    WORDS_FILE.write_text("\n".join(words_sorted), encoding="utf-8")
    PALOCHKA_WORDS_FILE.write_text("\n".join(palochka_words_sorted), encoding="utf-8")

    print()
    print("DONE")
    print(f"Rows processed: {total_rows}")
    print(f"Chechen phrases: {len(phrases_sorted)} -> {PHRASES_FILE}")
    print(f"Chechen words: {len(words_sorted)} -> {WORDS_FILE}")
    print(f"Palochka words: {len(palochka_words_sorted)} -> {PALOCHKA_WORDS_FILE}")


if __name__ == "__main__":
    main()