"""
dictionaries.py

Loads the rule dictionaries and data-driven fix tables from `rules_dir`
once and exposes them as an immutable-ish container:

- rules/palochka_words.txt, chechen_words.txt, chechen_phrases.txt
  (plain wordlists/corpus, unchanged from the original project)
- rules/common_word_fixes.yaml (moved out of
  correctors/common_words.py -- see that module's docstring)
- rules/known_suspicious_candidates.yaml (moved out of suspicious.py)

Replaces the original module-level `PALOCHKA_DICTIONARY = set()` global
and `load_palochka_words()` that re-read the file from a
current-working-directory-relative path on every call.

Backward compatibility: if the two YAML files aren't present in
rules_dir (e.g. an older rules/ directory, or a custom rules_dir with
only the wordlist files), Dictionaries.load() falls back to the
built-in defaults from correctors.common_words and suspicious --
adding the YAML files is purely additive, never a hard requirement.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


def _load_wordlist(path: Path) -> frozenset[str]:
    if not path.exists():
        return frozenset()

    words = set()
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            word = line.strip()
            if word:
                words.add(word.lower())

    return frozenset(words)


def _load_lines(path: Path) -> tuple[str, ...]:
    if not path.exists():
        return ()

    with path.open("r", encoding="utf-8", errors="replace") as f:
        return tuple(line.rstrip("\n") for line in f if line.strip())


def _load_common_word_fixes(path: Path) -> dict[str, str] | None:
    """Returns None (not {}) when the file is absent, so callers can
    distinguish "use built-in defaults" from "file exists but is empty"."""
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return dict(data.get("fixes") or {})


def _load_known_suspicious(
    path: Path,
) -> tuple[dict[str, tuple[str, ...]], frozenset[str]] | None:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    candidates = {
        word: tuple(cands)
        for word, cands in (data.get("known_suspicious_candidates") or {}).items()
    }
    whitelist = frozenset(data.get("whitelist") or [])
    return candidates, whitelist


def _build_phrase_bigrams(phrases: tuple[str, ...]) -> frozenset[tuple[str, str]]:
    """
    Builds a lowercase word-bigram index from the reference phrase
    corpus, for lightweight context-based disambiguation (see
    correctors/phrase_disambiguation.py): "does <candidate> next to
    this neighbor word actually occur somewhere in real Chechen text?"
    is a much cheaper question than full language modeling, and is
    enough to break ties between multiple dictionary-valid palochka
    candidates in the common case.

    Costs roughly 1-2 seconds for the ~113k-phrase corpus shipped with
    this package; this only runs once per rules_dir since
    Dictionaries.load() is cached (see load_dictionaries).
    """
    word_re = re.compile(r"\S+")
    strip_chars = ".,!?;:()[]{}«»\"'“”„-—"

    bigrams: set[tuple[str, str]] = set()
    for phrase in phrases:
        words = [w.strip(strip_chars).lower() for w in word_re.findall(phrase)]
        words = [w for w in words if w]
        for i in range(len(words) - 1):
            bigrams.add((words[i], words[i + 1]))

    return frozenset(bigrams)


@dataclass(frozen=True)
class Dictionaries:
    """
    palochka_words: lowercase set of known-good words containing Ӏ.
        Used for the "exactly one candidate matches -> auto-correct" rule.
    chechen_words: broader lowercase wordlist (may or may not contain Ӏ).
        General-purpose spellcheck dictionary (see
        correctors/general_word_fix.py, correctors/word_segmentation.py).
    chechen_phrases: raw reference phrases/sentences from the source corpus.
    phrase_bigrams: lowercase word-bigram index derived from
        chechen_phrases, for context-based disambiguation (see
        correctors/phrase_disambiguation.py).
    common_word_fixes: hand-verified (before -> after) whole-word OCR fixes.
        See correctors/common_words.py and rules/common_word_fixes.yaml.
    known_suspicious_candidates: word -> suggested correction(s), for
        cases the dictionary-candidate corrector can't disambiguate alone.
    suspicious_whitelist: words that must never be flagged as suspicious.
    """

    palochka_words: frozenset[str] = field(default_factory=frozenset)
    chechen_words: frozenset[str] = field(default_factory=frozenset)
    chechen_phrases: tuple[str, ...] = field(default_factory=tuple)
    phrase_bigrams: frozenset[tuple[str, str]] = field(default_factory=frozenset)
    common_word_fixes: dict[str, str] = field(default_factory=dict)
    known_suspicious_candidates: dict[str, tuple[str, ...]] = field(default_factory=dict)
    suspicious_whitelist: frozenset[str] = field(default_factory=frozenset)

    @classmethod
    def load(cls, rules_dir: Path) -> Dictionaries:
        rules_dir = Path(rules_dir)
        logger.debug("loading dictionaries from %s", rules_dir)

        common_word_fixes = _load_common_word_fixes(rules_dir / "common_word_fixes.yaml")
        if common_word_fixes is None:
            from .correctors.common_words import COMMON_WORD_FIXES

            logger.debug(
                "common_word_fixes.yaml not found in %s; using %d built-in defaults",
                rules_dir,
                len(COMMON_WORD_FIXES),
            )
            common_word_fixes = COMMON_WORD_FIXES
        else:
            logger.debug(
                "loaded %d common word fixes from %s",
                len(common_word_fixes),
                rules_dir / "common_word_fixes.yaml",
            )

        known_suspicious = _load_known_suspicious(rules_dir / "known_suspicious_candidates.yaml")
        if known_suspicious is None:
            from .suspicious import DEFAULT_WHITELIST, KNOWN_SUSPICIOUS_CANDIDATES

            logger.debug(
                "known_suspicious_candidates.yaml not found in %s; using built-in defaults",
                rules_dir,
            )
            known_suspicious_candidates: dict[str, tuple[str, ...]] = {
                word: tuple(cands) for word, cands in KNOWN_SUSPICIOUS_CANDIDATES.items()
            }
            suspicious_whitelist = DEFAULT_WHITELIST
        else:
            known_suspicious_candidates, suspicious_whitelist = known_suspicious

        palochka_words = _load_wordlist(rules_dir / "palochka_words.txt")
        chechen_words = _load_wordlist(rules_dir / "chechen_words.txt")
        chechen_phrases = _load_lines(rules_dir / "chechen_phrases.txt")
        phrase_bigrams = _build_phrase_bigrams(chechen_phrases)

        logger.debug(
            "dictionaries loaded: %d palochka words, %d general words, "
            "%d reference phrases (%d bigrams)",
            len(palochka_words),
            len(chechen_words),
            len(chechen_phrases),
            len(phrase_bigrams),
        )

        return cls(
            palochka_words=palochka_words,
            chechen_words=chechen_words,
            chechen_phrases=chechen_phrases,
            phrase_bigrams=phrase_bigrams,
            common_word_fixes=common_word_fixes,
            known_suspicious_candidates=known_suspicious_candidates,
            suspicious_whitelist=suspicious_whitelist,
        )

    @classmethod
    def empty(cls) -> Dictionaries:
        return cls()


@lru_cache(maxsize=8)
def _load_cached(rules_dir_str: str) -> Dictionaries:
    return Dictionaries.load(Path(rules_dir_str))


def load_dictionaries(rules_dir: Path, use_cache: bool = True) -> Dictionaries:
    """
    Loads dictionaries, cached per rules_dir path so that repeated
    ChechenOcrProcessor construction (e.g. one per CLI invocation)
    doesn't re-read multi-megabyte wordlists every time within the
    same process.
    """
    if not use_cache:
        return Dictionaries.load(rules_dir)
    return _load_cached(str(Path(rules_dir).resolve()))
