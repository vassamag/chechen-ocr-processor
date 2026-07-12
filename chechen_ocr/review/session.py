"""
session.py

Persistence/resume support for reviewing large, multi-block documents
across sessions, per project discussion:

- A block's identity is its position in the document (or source photo
  filename, when available) -- NOT the page number printed on it,
  since that can be missing or misread (this project has repeated
  real examples of both). The page number is a separate, editable/
  flaggable field on the block, independent of its identity.
- Tracking is per LINE, not per block/page: for each line we keep
  both what the corrector most recently produced and what's currently
  saved. A line where those still match hasn't been touched by a
  person and is safe to reprocess (e.g. after a corrector
  improvement); a line where they differ was edited by a person and
  is left alone by any future automated run, regardless of corrector
  version, until the person explicitly resets it.
- The last block/line position edited is saved and restored on
  reopening, so review can resume where it left off.

This module has no GUI dependency -- it's plain data + functions, so
the GUI (and, if useful later, a CLI) can both build on it without
duplicating the logic.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..processor import ChechenOcrProcessor


@dataclass
class LineRecord:
    """One line within a block. `corrector_output` is what the
    correction pipeline most recently produced for this line;
    `saved_text` is what's currently saved (equal to corrector_output
    unless a person has edited it)."""

    corrector_output: str
    saved_text: str

    @property
    def is_edited(self) -> bool:
        return self.saved_text != self.corrector_output

    def to_dict(self) -> dict[str, str]:
        return {"corrector_output": self.corrector_output, "saved_text": self.saved_text}

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> LineRecord:
        return cls(corrector_output=data["corrector_output"], saved_text=data["saved_text"])


@dataclass
class BlockRecord:
    """One block (typically one page/photo). `block_id` is the stable
    identity used for tracking -- a sequential position or a source
    filename, never the page number. `page_number` and
    `page_verified` are a separate, editable field describing what's
    printed/recognized on the block, independent of `block_id`."""

    block_id: str
    lines: list[LineRecord]
    page_number: str = ""
    page_verified: bool = False

    def to_dict(self) -> dict:
        return {
            "block_id": self.block_id,
            "page_number": self.page_number,
            "page_verified": self.page_verified,
            "lines": [line.to_dict() for line in self.lines],
        }

    @classmethod
    def from_dict(cls, data: dict) -> BlockRecord:
        return cls(
            block_id=data["block_id"],
            page_number=data.get("page_number", ""),
            page_verified=data.get("page_verified", False),
            lines=[LineRecord.from_dict(line) for line in data["lines"]],
        )

    @property
    def text(self) -> str:
        return "\n".join(line.saved_text for line in self.lines)

    @property
    def has_any_edits(self) -> bool:
        return any(line.is_edited for line in self.lines)


@dataclass
class ReviewSession:
    """The full persisted state for one document under review."""

    blocks: list[BlockRecord] = field(default_factory=list)
    last_position: tuple[str, int] | None = None  # (block_id, line_index)

    def find_block(self, block_id: str) -> BlockRecord | None:
        for block in self.blocks:
            if block.block_id == block_id:
                return block
        return None

    def to_dict(self) -> dict:
        return {
            "blocks": [block.to_dict() for block in self.blocks],
            "last_position": list(self.last_position) if self.last_position else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ReviewSession:
        last_position = data.get("last_position")
        return cls(
            blocks=[BlockRecord.from_dict(b) for b in data["blocks"]],
            last_position=tuple(last_position) if last_position else None,
        )

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> ReviewSession:
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))


def session_path_for(output_path: Path) -> Path:
    """The sidecar file a session is stored under, next to the actual
    output file (never mixed into the document itself)."""
    return output_path.with_suffix(output_path.suffix + ".review_session.json")


def build_session_from_blocks(
    block_texts: list[tuple[str, str]],
) -> ReviewSession:
    """
    Builds a fresh ReviewSession from (block_id, text) pairs -- e.g.
    the output of a first corrector pass, one entry per page/photo.
    Every line starts unedited (saved_text == corrector_output).
    """
    blocks = []
    for block_id, text in block_texts:
        lines = [LineRecord(corrector_output=line, saved_text=line) for line in text.split("\n")]
        blocks.append(BlockRecord(block_id=block_id, lines=lines))
    return ReviewSession(blocks=blocks)


def reprocess_session(
    session: ReviewSession,
    processor: ChechenOcrProcessor,
    ocr_engine_name: str | None = None,
) -> ReviewSession:
    """
    Re-runs the correction pipeline over every block, but only on
    lines that haven't been edited by a person (saved_text still
    equals the corrector_output from the last run). Edited lines are
    left completely untouched, regardless of what a newer corrector
    version would now produce for them.
    """
    new_blocks = []
    for block in session.blocks:
        new_lines = []
        for line in block.lines:
            if line.is_edited:
                new_lines.append(line)
                continue
            result = processor.process_text(line.saved_text, ocr_engine_name=ocr_engine_name)
            new_lines.append(
                LineRecord(corrector_output=result.corrected_text, saved_text=result.corrected_text)
            )
        new_blocks.append(
            BlockRecord(
                block_id=block.block_id,
                page_number=block.page_number,
                page_verified=block.page_verified,
                lines=new_lines,
            )
        )
    return ReviewSession(blocks=new_blocks, last_position=session.last_position)


def split_text_into_blocks(text: str) -> list[tuple[str, str, str]]:
    """
    Splits text into (block_id, page_number, block_text) triples using
    the same page-marker detection build_page_index() already uses
    (both the "===== Страница N =====" format and the bold-digit-line
    fallback). block_id is the block's ORDINAL POSITION (as a string),
    never the page number itself -- consistent with this module's
    identity rule. If no page markers are found at all, the whole text
    is treated as a single block.
    """
    # Imported here, not at module level, to avoid a circular import
    # (schema.py doesn't need to know about session.py).
    from .schema import build_page_index

    spans = build_page_index(text)
    if not spans:
        return [("0", "", text)]

    return [
        (str(i), span.page, text[span.start : span.end].strip("\n")) for i, span in enumerate(spans)
    ]


def build_session_from_text(text: str) -> ReviewSession:
    """Convenience wrapper: splits text into blocks by page markers
    (see split_text_into_blocks) and builds a fresh, fully-unedited
    ReviewSession, with page_number/page_verified set from the
    detected markers."""
    blocks = []
    for block_id, page_number, block_text in split_text_into_blocks(text):
        lines = [
            LineRecord(corrector_output=line, saved_text=line) for line in block_text.split("\n")
        ]
        blocks.append(
            BlockRecord(
                block_id=block_id,
                page_number=page_number,
                page_verified=False,
                lines=lines,
            )
        )
    return ReviewSession(blocks=blocks)


def sync_session_with_edited_text(session: ReviewSession, edited_text: str) -> ReviewSession:
    """
    Updates a session's saved_text to reflect manual edits made to the
    FULL, already-corrected text (e.g. typed directly into the GUI's
    Corrected Text box), re-splitting it into blocks the same way the
    session was originally built. Blocks are matched by ORDINAL
    POSITION (not page number, not content), consistent with this
    module's identity rule -- if the number of detected blocks
    changed (a page marker was added/removed by the edit), the extra
    or missing blocks are handled by truncating/padding rather than
    guessing a correspondence.

    Within a matched block: if the edited block's line count still
    matches the original, each line's saved_text is updated
    individually (preserving per-line edit tracking). If the line
    count changed, the whole block collapses to a single line and is
    treated as edited -- a precise line-by-line correspondence can't
    be inferred once lines have been added or removed, so the safer
    choice is to lock the whole block rather than risk mis-attributing
    an edit to the wrong line.
    """
    new_chunks = split_text_into_blocks(edited_text)
    new_blocks = []

    for i, block in enumerate(session.blocks):
        if i >= len(new_chunks):
            # Block was removed from the edited text entirely --
            # keep it as last-known-saved, don't invent content.
            new_blocks.append(block)
            continue

        _, new_page_number, new_block_text = new_chunks[i]
        new_physical_lines = new_block_text.split("\n")

        if len(new_physical_lines) == len(block.lines):
            new_lines = [
                LineRecord(corrector_output=old.corrector_output, saved_text=new_line)
                for old, new_line in zip(block.lines, new_physical_lines, strict=True)
            ]
        else:
            combined_corrector_output = "\n".join(line.corrector_output for line in block.lines)
            new_lines = [
                LineRecord(corrector_output=combined_corrector_output, saved_text=new_block_text)
            ]

        new_blocks.append(
            BlockRecord(
                block_id=block.block_id,
                page_number=new_page_number or block.page_number,
                page_verified=block.page_verified,
                lines=new_lines,
            )
        )

    return ReviewSession(blocks=new_blocks, last_position=session.last_position)
