from pathlib import Path

from chechen_ocr.dictionaries import Dictionaries


def test_falls_back_to_builtin_defaults_when_yaml_files_absent(tmp_path):
    # An empty rules_dir has none of the YAML/txt files.
    dictionaries = Dictionaries.load(tmp_path)

    from chechen_ocr.correctors.common_words import COMMON_WORD_FIXES
    from chechen_ocr.suspicious import DEFAULT_WHITELIST, KNOWN_SUSPICIOUS_CANDIDATES

    assert dictionaries.common_word_fixes == COMMON_WORD_FIXES
    assert dictionaries.suspicious_whitelist == DEFAULT_WHITELIST
    assert dictionaries.known_suspicious_candidates == {
        word: tuple(cands) for word, cands in KNOWN_SUSPICIOUS_CANDIDATES.items()
    }


def test_loads_common_word_fixes_from_yaml(tmp_path: Path):
    (tmp_path / "common_word_fixes.yaml").write_text(
        "fixes:\n  foo: bar\n  baz: qux\n", encoding="utf-8"
    )

    dictionaries = Dictionaries.load(tmp_path)

    assert dictionaries.common_word_fixes == {"foo": "bar", "baz": "qux"}


def test_loads_known_suspicious_candidates_from_yaml(tmp_path: Path):
    (tmp_path / "known_suspicious_candidates.yaml").write_text(
        "known_suspicious_candidates:\n"
        "  bad1: [good1]\n"
        "  bad2: [good2a, good2b]\n"
        "whitelist:\n"
        "  - keepme\n",
        encoding="utf-8",
    )

    dictionaries = Dictionaries.load(tmp_path)

    assert dictionaries.known_suspicious_candidates == {
        "bad1": ("good1",),
        "bad2": ("good2a", "good2b"),
    }
    assert dictionaries.suspicious_whitelist == frozenset({"keepme"})


def test_yaml_fixes_take_priority_over_builtin_defaults(tmp_path: Path):
    # A custom rules_dir with ONLY a common_word_fixes.yaml should use
    # exactly that data, not merge with the built-in COMMON_WORD_FIXES.
    (tmp_path / "common_word_fixes.yaml").write_text(
        "fixes:\n  onlyThis: onlyThat\n", encoding="utf-8"
    )

    dictionaries = Dictionaries.load(tmp_path)

    assert dictionaries.common_word_fixes == {"onlyThis": "onlyThat"}


def test_real_rules_dir_yaml_files_match_builtin_defaults():
    """
    The actual rules/*.yaml files shipped with this package should be
    an exact, lossless extraction of the built-in Python defaults --
    this test guards against manual edits silently drifting from the
    values the package was shipped with.
    """
    rules_dir = Path(__file__).resolve().parents[1] / "rules"
    dictionaries = Dictionaries.load(rules_dir)

    from chechen_ocr.correctors.common_words import COMMON_WORD_FIXES
    from chechen_ocr.suspicious import DEFAULT_WHITELIST, KNOWN_SUSPICIOUS_CANDIDATES

    assert dictionaries.common_word_fixes == COMMON_WORD_FIXES
    assert dictionaries.suspicious_whitelist == DEFAULT_WHITELIST
    assert dictionaries.known_suspicious_candidates == {
        word: tuple(cands) for word, cands in KNOWN_SUSPICIOUS_CANDIDATES.items()
    }
