"""
Pattern-based palochka correction: a base consonant that can take a
palochka in Chechen (г, к, п, т, х, ц, ч, д, б and uppercase forms),
directly followed by a common OCR lookalike character for Ӏ
(1, l, I, |, !, [, ]  and a few Cyrillic look-alikes), is normalized to
<consonant> + Ӏ.

Examples: "г!" -> "гӀ", "к1" -> "кӀ", "х|" -> "хӀ".

This is a Tesseract/Latin-OCR-specific heuristic: it assumes the OCR
engine rendered the palochka as a Latin-alphabet-shaped glyph attached
to the preceding consonant. Vision-API-style engines that "read" the
word semantically rarely produce this exact artifact, so this
corrector is a good candidate to disable for such engines (see
processor.build_pipeline).

Ported as-is from process.py::normalize_palochka (pattern part).
"""

from __future__ import annotations

import re

from ..core import Correction, CorrectionResult, PipelineContext

BASE_LETTERS = "гкптхцчдбГКПТХЦЧДБ"
LOOKALIKES = "Iil1|![]ЇїЈј"

_PATTERN = re.compile(f"([{BASE_LETTERS}])([{re.escape(LOOKALIKES)}])")


class PatternBasedPalochka:
    name = "palochka_pattern"

    def apply(self, text: str, ctx: PipelineContext) -> CorrectionResult:
        corrections: list[Correction] = []

        def repl(match: re.Match[str]) -> str:
            before = match.group(0)
            after = match.group(1) + "Ӏ"
            corrections.append(
                Correction(
                    rule=self.name,
                    before=before,
                    after=after,
                    position=match.start(),
                )
            )
            return after

        new_text = _PATTERN.sub(repl, text)
        return CorrectionResult(text=new_text, corrections=corrections)
