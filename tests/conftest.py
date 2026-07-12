from __future__ import annotations

import pytest

from chechen_ocr.config import Settings
from chechen_ocr.core import PipelineContext
from chechen_ocr.dictionaries import Dictionaries


# NOTE on a real Unicode quirk this project has to live with:
# Ӏ (Cyrillic Letter Palochka, U+04C0) is defined by Unicode as an
# uppercase-only letter. Calling .lower() on it yields a DIFFERENT
# code point, ӏ (Cyrillic Small Letter Palochka, U+04CF) -- not "the
# same Ӏ, just lowercase". Dictionaries.load() lowercases every word
# it reads (for case-insensitive lookups), so any Ӏ inside a
# dictionary word is silently stored as U+04CF internally.
# generate_palochka_candidates() always *produces* U+04C0 (it's the
# canonical, correct form used in real text), and the corrector
# compares `candidate.lower() in dictionary` -- i.e. it lowercases the
# candidate (U+04C0 -> U+04CF) before checking membership. Both sides
# go through the same transform, so matching still works correctly;
# but any dictionary built by hand for a test MUST go through the same
# .lower() step, or comparisons will silently fail. Fixtures below
# call .lower() explicitly for this reason -- do not remove it.
@pytest.fixture
def tiny_dictionaries() -> Dictionaries:
    """A small, hand-picked dictionary for deterministic unit tests."""
    return Dictionaries(
        palochka_words=frozenset(w.lower() for w in ("кӀант", "хӀара", "хӀун", "йоӀ")),
        chechen_words=frozenset(),
        chechen_phrases=(),
        known_suspicious_candidates={"Аълбикин": ("Аьлбикин",)},
        suspicious_whitelist=frozenset({"Маьлха-Аьзни"}),
    )


@pytest.fixture
def ambiguous_dictionaries() -> Dictionaries:
    """
    A dictionary where a single OCR-damaged token ("к1а]н") generates
    two distinct dictionary-valid candidates ("кӀа]н" via '1'->Ӏ, and
    "к1аӀн" via ']'->Ӏ), to test that the disambiguation rule refuses
    to guess when more than one candidate is plausible.
    """
    return Dictionaries(
        palochka_words=frozenset(w.lower() for w in ("кӀа]н", "к1аӀн")),
        chechen_words=frozenset(),
        chechen_phrases=(),
    )


def make_ctx(
    dictionaries: Dictionaries, ocr_engine_name: str | None = "tesseract"
) -> PipelineContext:
    return PipelineContext(
        settings=Settings.default(),
        dictionaries=dictionaries,
        ocr_engine_name=ocr_engine_name,
    )


@pytest.fixture
def ctx_factory():
    return make_ctx
