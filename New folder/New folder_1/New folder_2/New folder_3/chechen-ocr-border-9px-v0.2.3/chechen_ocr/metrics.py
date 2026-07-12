"""
metrics.py

Aggregated, structured metrics for a single ProcessedDocument, meant
for monitoring quality across many documents (e.g. a batch job
processing hundreds of scanned pages) rather than inspecting one
document's corrections/suspicious lists by hand.

The motivating use case (see the refactor roadmap discussion): a sudden
spike in suspicious_ratio for one page in a batch usually means "this
scan is low quality," not "a new error pattern appeared" -- having a
single number per document makes that kind of anomaly visible without
reading every corrections/suspicious list individually.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .core import Correction

_LOOKALIKE_NO_PALOCHKA_RE = re.compile(r"^[^\W\d_]*[Iil1\|!\[\]ЇїЈј][^\W\d_]*$", re.UNICODE)
_WORD_RE = re.compile(r"\S+", flags=re.UNICODE)


@dataclass
class DocumentMetrics:
    total_words: int
    total_corrections: int
    corrections_by_rule: dict[str, int] = field(default_factory=dict)
    suspicious_count: int = 0
    suspicious_ratio: float = 0.0
    unconverted_lookalike_count: int = 0

    @property
    def corrections_per_1000_words(self) -> float:
        if self.total_words == 0:
            return 0.0
        return 1000 * self.total_corrections / self.total_words


def compute_metrics(
    corrected_text: str,
    corrections: list[Correction],
    suspicious_count: int,
) -> DocumentMetrics:
    """
    Builds a DocumentMetrics summary from the pieces of a
    ProcessedDocument. Kept as a plain function (not a ProcessedDocument
    method) so it has no dependency on processor.py, avoiding a circular
    import -- ChechenOcrProcessor.compute_metrics() is a thin wrapper
    around this.
    """
    total_words = len(_WORD_RE.findall(corrected_text))

    corrections_by_rule: dict[str, int] = {}
    for c in corrections:
        corrections_by_rule[c.rule] = corrections_by_rule.get(c.rule, 0) + 1

    unconverted = sum(
        1
        for w in _WORD_RE.findall(corrected_text)
        if "Ӏ" not in w and _LOOKALIKE_NO_PALOCHKA_RE.match(w)
    )

    suspicious_ratio = suspicious_count / total_words if total_words else 0.0

    return DocumentMetrics(
        total_words=total_words,
        total_corrections=len(corrections),
        corrections_by_rule=corrections_by_rule,
        suspicious_count=suspicious_count,
        suspicious_ratio=suspicious_ratio,
        unconverted_lookalike_count=unconverted,
    )
