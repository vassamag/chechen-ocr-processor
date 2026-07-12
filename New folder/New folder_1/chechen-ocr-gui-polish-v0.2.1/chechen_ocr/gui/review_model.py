"""
review_model.py

Helpers for displaying ReviewRow objects in a Tkinter Treeview and
applying in-GUI edits, kept separate from any Tkinter import so the
logic is independently testable without a display.

The GUI lets a person edit `decision`/`replacement` directly in the
table (rather than exporting a CSV, editing externally, and importing
it back) -- but the underlying apply step is exactly
review.apply_review_rows, unchanged; this module only adapts data
shapes.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..review.schema import ReviewRow

TREEVIEW_COLUMNS = ("id", "page", "word", "reason", "candidates", "decision", "replacement")

VALID_DECISIONS = ("pending", "replace", "reject")


@dataclass
class EditableReviewRow:
    """A ReviewRow plus mutable decision/replacement fields the GUI
    edits in place, kept as a separate wrapper so the original
    ReviewRow (and its context snippets) stay intact for reference."""

    row: ReviewRow
    decision: str = "pending"
    replacement: str = ""

    def display_values(self) -> tuple[str, ...]:
        return (
            str(self.row.id),
            self.row.page,
            self.row.word,
            self.row.reason,
            self.row.candidates,
            self.decision,
            self.replacement,
        )

    def as_apply_dict(self) -> dict[str, str]:
        """Shape expected by review.apply_review_rows: the original
        row's fields, with this GUI's edited decision/replacement."""
        d = self.row.as_csv_dict()
        d["decision"] = self.decision
        d["replacement"] = self.replacement
        return d


@dataclass
class ReviewTableModel:
    """Holds the editable rows for one processed document and the
    handful of small queries/mutations the GUI needs."""

    items: list[EditableReviewRow] = field(default_factory=list)

    @classmethod
    def from_rows(cls, rows: list[ReviewRow]) -> ReviewTableModel:
        return cls(items=[EditableReviewRow(row=r) for r in rows])

    def find_by_id(self, row_id: str) -> EditableReviewRow | None:
        for item in self.items:
            if str(item.row.id) == str(row_id):
                return item
        return None

    def set_decision(self, row_id: str, decision: str) -> None:
        if decision not in VALID_DECISIONS:
            raise ValueError(f"Invalid decision {decision!r}; must be one of {VALID_DECISIONS}")
        item = self.find_by_id(row_id)
        if item is not None:
            item.decision = decision

    def set_replacement(self, row_id: str, replacement: str) -> None:
        item = self.find_by_id(row_id)
        if item is not None:
            item.replacement = replacement

    def pending_count(self) -> int:
        return sum(1 for item in self.items if item.decision == "pending")

    def as_apply_dicts(self) -> list[dict[str, str]]:
        return [item.as_apply_dict() for item in self.items]
