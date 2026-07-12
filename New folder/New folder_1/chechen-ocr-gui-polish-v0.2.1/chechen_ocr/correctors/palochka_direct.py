"""
Direct, unconditional replacement of characters that are visually
identical (or near-identical) to the Chechen palochka Ӏ (U+04C0):

    І (Cyrillic byelorussian-ukrainian I) -> Ӏ
    і (lowercase of the above)             -> Ӏ
    ӏ (Ossetian/Karachay-Balkar palochka)   -> Ӏ

This is the highest-confidence, lowest-risk correction in the whole
pipeline: these are genuinely different Unicode code points that are
rendered identically in most fonts, so replacing them carries no
disambiguation risk. Ported as-is from process.py::normalize_palochka
(direct_replacements part).
"""

from __future__ import annotations

from ..core import Correction, CorrectionResult, PipelineContext

DIRECT_REPLACEMENTS = {
    "І": "Ӏ",
    "і": "Ӏ",
    "ӏ": "Ӏ",
}


class DirectPalochkaLookalikes:
    name = "palochka_direct"

    def apply(self, text: str, ctx: PipelineContext) -> CorrectionResult:
        corrections: list[Correction] = []

        for before, after in DIRECT_REPLACEMENTS.items():
            count = text.count(before)
            if count:
                text = text.replace(before, after)
                corrections.append(Correction(rule=self.name, before=before, after=after))

        return CorrectionResult(text=text, corrections=corrections)
