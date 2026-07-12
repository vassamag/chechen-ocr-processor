"""
core.py

Base data types and the Corrector / Pipeline abstractions used across
the whole chechen_ocr package.

Design goals (see refactor discussion):
- No module-level global state (no CORRECTION_LOG / SUSPICIOUS_LOG globals).
- Every correction step is a small, independently testable object
  implementing the `Corrector` protocol.
- The Pipeline composes correctors in a configurable order and collects
  a structured, serializable log of every change.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from .config import Settings
from .dictionaries import Dictionaries


@dataclass(frozen=True)
class Correction:
    """A single atomic text change made by a corrector."""

    rule: str
    before: str
    after: str
    # Position is best-effort: some correctors work on whole-text regex
    # substitutions and cannot cheaply report an exact offset. -1 means
    # "unknown / not tracked".
    position: int = -1


@dataclass
class CorrectionResult:
    text: str
    corrections: list[Correction] = field(default_factory=list)

    def extend(self, other: CorrectionResult) -> CorrectionResult:
        return CorrectionResult(
            text=other.text,
            corrections=self.corrections + other.corrections,
        )


@dataclass
class SuspiciousWord:
    word: str
    reason: str
    candidates: list[str] = field(default_factory=list)


@dataclass
class PipelineContext:
    """
    Everything a Corrector might need, besides the text itself.

    Loaded once per Processor instance (not per call), so dictionaries
    are shared across many process_text() / process_image() calls.
    """

    settings: Settings
    dictionaries: Dictionaries
    # Name of the OCR engine that produced the text, if any.
    # Lets a Pipeline decide to skip/enable certain correctors
    # (e.g. Tesseract-specific lookalike fixes are pointless for a
    # Vision-API engine that rarely confuses "I" and "Ӏ").
    ocr_engine_name: str | None = None


@runtime_checkable
class Corrector(Protocol):
    """
    A single, independently testable correction step.

    Implementations MUST be pure functions of (text, ctx) -> CorrectionResult.
    They must not mutate global state and must not depend on call order
    beyond what the Pipeline guarantees (sequential, in the given order).
    """

    name: str

    def apply(self, text: str, ctx: PipelineContext) -> CorrectionResult: ...


class Pipeline:
    """Runs a sequence of Correctors and merges their correction logs."""

    def __init__(self, correctors: list[Corrector]):
        self.correctors = correctors

    def run(self, text: str, ctx: PipelineContext) -> CorrectionResult:
        result = CorrectionResult(text=text, corrections=[])
        for corrector in self.correctors:
            step_result = corrector.apply(result.text, ctx)
            result = CorrectionResult(
                text=step_result.text,
                corrections=result.corrections + step_result.corrections,
            )
        return result

    def corrector_names(self) -> list[str]:
        return [c.name for c in self.correctors]
