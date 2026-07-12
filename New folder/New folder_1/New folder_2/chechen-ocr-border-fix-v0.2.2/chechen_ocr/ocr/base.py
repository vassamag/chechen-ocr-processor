"""
base.py

The OcrEngine protocol decouples "getting raw text out of an image"
from "cleaning up Chechen-specific OCR artifacts". The Pipeline of
Correctors never needs to know which engine produced the text; the
engine's name is passed through PipelineContext.ocr_engine_name so
that build_pipeline() can enable/disable engine-specific correctors
(see processor.py).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@dataclass
class OcrResult:
    text: str
    engine_name: str
    confidence: float | None = None
    raw_response: Any | None = None
    # Best-effort token/cost accounting for API-based engines (None for
    # engines that don't have a meaningful notion of this, e.g. Tesseract).
    # See vision_api_engine.extract_usage() for how this gets populated
    # for OpenAI-compatible responses.
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


@runtime_checkable
class OcrEngine(Protocol):
    name: str

    def recognize(self, image_path: Path, lang: str = "rus") -> OcrResult: ...
