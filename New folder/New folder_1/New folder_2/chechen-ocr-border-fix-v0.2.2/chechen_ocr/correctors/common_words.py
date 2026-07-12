"""
Conservative, hand-curated whole-word replacements for common OCR
mistakes that the pattern-based and dictionary-candidate correctors
don't reliably catch (e.g. multi-character corruption, or words with
more than one plausible palochka position).

This is data, not logic. The canonical copy of this data now lives in
rules/common_word_fixes.yaml (see dictionaries.Dictionaries.load) --
CommonWordFixList reads from ctx.dictionaries.common_word_fixes at
apply() time. COMMON_WORD_FIXES below is kept only as the built-in
*fallback* default for when that YAML file isn't present (e.g. a
rules_dir that predates this change), and as a convenience default for
tests that construct CommonWordFixList() directly without a
PipelineContext-backed rules_dir. Edit the YAML file, not this
constant, to change real behavior.

Ported as-is from process.py::fix_common_chechen_ocr_words.
"""

from __future__ import annotations

from ..core import Correction, CorrectionResult, PipelineContext

# NOTE: this dict is the "data" half of this corrector. Moving it to a
# YAML/CSV file under rules/ later is a pure data migration -- load it
# in __init__ instead of importing this constant, keep the .apply()
# logic unchanged.
COMMON_WORD_FIXES: dict[str, str] = {
    # h/palochka words
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


class CommonWordFixList:
    """
    If constructed with an explicit `fixes` dict, that dict is used
    unconditionally (handy for tests or a custom pipeline). Otherwise,
    at apply() time, the fixes come from
    `ctx.dictionaries.common_word_fixes` -- which is populated from
    rules/common_word_fixes.yaml if present, or the COMMON_WORD_FIXES
    constant above otherwise (see dictionaries.Dictionaries.load).
    This means the default deployment reads fixes from data, while
    still working with zero configuration if that YAML file is
    missing (e.g. an older rules/ directory).
    """

    name = "common_word_fix"

    def __init__(self, fixes: dict[str, str] | None = None):
        self._explicit_fixes = fixes

    def apply(self, text: str, ctx: PipelineContext) -> CorrectionResult:
        fixes = self._explicit_fixes
        if fixes is None:
            fixes = ctx.dictionaries.common_word_fixes or COMMON_WORD_FIXES

        # Longer keys first, to avoid partial-replacement issues
        # (e.g. "хТокхуьнгахь" must be tried before "хТокху").
        ordered_fixes = sorted(fixes.items(), key=lambda kv: len(kv[0]), reverse=True)

        corrections: list[Correction] = []
        for before, after in ordered_fixes:
            count = text.count(before)
            if count:
                text = text.replace(before, after)
                corrections.append(Correction(rule=self.name, before=before, after=after))

        return CorrectionResult(text=text, corrections=corrections)
