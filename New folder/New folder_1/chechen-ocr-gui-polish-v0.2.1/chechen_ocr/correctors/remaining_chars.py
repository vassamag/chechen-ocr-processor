"""
Cautious final normalization pass for remaining OCR artifacts that the
earlier correctors don't touch:

1) Ї / ї -> Ӏ inside Cyrillic/Chechen words.
2) ! -> Ӏ only when it is very likely a damaged palochka, not real
   punctuation (context-sensitive: between Cyrillic letters, before a
   Cyrillic letter inside a token, or at the end of a small whitelist
   of known palochka-final word stems).
3) ] is removed only in clearly suspicious OCR positions (adjacent to
   Cyrillic text, isolated among Cyrillic context, etc).
4) | is intentionally never touched here (used in page headers like
   "===== Страница 11 | IMG-...jpg =====" in the source pipeline;
   downstream text-mode callers should strip such service lines before
   running this pipeline -- see processor.ChechenOcrProcessor).

Ported from src/normalize_remaining_ocr_chars_v2.py, restructured as a
single stateless Corrector. Position-accurate logging is preserved
since it was one of the genuinely useful features of the original
script (used for human review of individual changes).
"""

from __future__ import annotations

import re

from ..core import Correction, CorrectionResult, PipelineContext

CYR = "А-Яа-яЁёІіЇїӀӏ"

FINAL_PALOCHKA_STEMS = {
    "йо",
    "ио",
    "не",
    "барх",
    "мостаг",
    "моста",
    "доттаг",
    "хорт",
    "бурт",
}

_CYR_RE = re.compile(rf"[{CYR}]")


def _is_cyr(ch: str) -> bool:
    return bool(ch) and _CYR_RE.match(ch) is not None


def _has_cyr(s: str) -> bool:
    return _CYR_RE.search(s) is not None


TOKEN_CHARS = CYR + "A-Za-z0-9_\\-'"
_TOKEN_CHAR_RE = re.compile(rf"[{TOKEN_CHARS}]")


def _is_token_char(ch: str) -> bool:
    return bool(ch) and _TOKEN_CHAR_RE.match(ch) is not None


def _token_bounds(text: str, pos: int) -> tuple[int, int]:
    start = pos
    while start > 0 and _is_token_char(text[start - 1]):
        start -= 1
    end = pos + 1
    while end < len(text) and _is_token_char(text[end]):
        end += 1
    return start, end


def _should_replace_bang(text: str, pos: int) -> tuple[bool, str]:
    prev_ch = text[pos - 1] if pos > 0 else ""
    next_ch = text[pos + 1] if pos + 1 < len(text) else ""

    start, end = _token_bounds(text, pos)
    token = text[start:end]
    before = token[: pos - start]
    after = token[pos - start + 1 :]

    if _is_cyr(prev_ch) and _is_cyr(next_ch):
        return True, "bang_between_cyrillic_letters"

    if (
        next_ch
        and _is_cyr(next_ch)
        and before
        and not before.endswith((" ", "\n", "\t"))
        and (_has_cyr(before) or re.search(r"[A-Za-z]$", before))
    ):
        return True, "bang_before_cyrillic_inside_token"

    if not before and _is_cyr(next_ch):
        return True, "bang_initial_before_cyrillic"

    if before and not after and _is_cyr(prev_ch):
        stem = before.lower().strip("-'")
        if stem in FINAL_PALOCHKA_STEMS:
            return True, "bang_final_known_palochka_word"

    return False, ""


class RemainingCharsCleanup:
    name = "remaining_chars_cleanup"

    def apply(self, text: str, ctx: PipelineContext) -> CorrectionResult:
        corrections: list[Correction] = []
        text = self._normalize_yi_and_bang(text, corrections)
        text = self._remove_bracket_noise(text, corrections)
        return CorrectionResult(text=text, corrections=corrections)

    # -- Ї / ї and ! --------------------------------------------------

    def _normalize_yi_and_bang(self, text: str, corrections: list[Correction]) -> str:
        chars = list(text)

        for i, ch in enumerate(chars):
            if ch in ("Ї", "ї"):
                start, end = _token_bounds(text, i)
                if _has_cyr(text[start:end]):
                    corrections.append(
                        Correction(
                            rule="yi_variant_inside_cyrillic_token",
                            before=ch,
                            after="Ӏ",
                            position=i,
                        )
                    )
                    chars[i] = "Ӏ"

        intermediate = "".join(chars)
        chars = list(intermediate)

        for i, ch in enumerate(chars):
            if ch != "!":
                continue
            ok, rule = _should_replace_bang(intermediate, i)
            if ok:
                corrections.append(Correction(rule=rule, before="!", after="Ӏ", position=i))
                chars[i] = "Ӏ"

        return "".join(chars)

    # -- ] --------------------------------------------------------------

    def _remove_bracket_noise(self, text: str, corrections: list[Correction]) -> str:
        chars = list(text)
        remove_positions: set[int] = set()

        for i, ch in enumerate(chars):
            if ch != "]":
                continue

            prev_ch = chars[i - 1] if i > 0 else ""
            next_ch = chars[i + 1] if i + 1 < len(chars) else ""

            near_left = text[max(0, i - 25) : i]
            near_right = text[i + 1 : min(len(text), i + 26)]
            near = near_left + near_right

            reason = ""
            if _is_cyr(prev_ch) or _is_cyr(next_ch):
                reason = "right_bracket_adjacent_to_cyrillic"
            elif prev_ch.isdigit() and _has_cyr(near_right):
                reason = "right_bracket_after_digit_near_cyrillic"
            elif (
                _has_cyr(near)
                and (not prev_ch or prev_ch.isspace())
                and (not next_ch or next_ch.isspace())
            ):
                reason = "isolated_right_bracket_in_cyrillic_context"
            elif prev_ch in "-=—–" and _has_cyr(near):
                reason = "right_bracket_after_dash_or_equals_in_cyrillic_context"

            if reason:
                remove_positions.add(i)
                corrections.append(Correction(rule=reason, before="]", after="", position=i))

        if not remove_positions:
            return text

        return "".join(ch for i, ch in enumerate(chars) if i not in remove_positions)
