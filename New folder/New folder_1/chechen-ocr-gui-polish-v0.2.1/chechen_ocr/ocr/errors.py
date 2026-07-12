"""
errors.py

Custom exceptions for OcrEngine implementations. Kept independent of
any specific provider SDK (openai, anthropic, google, ...) since
OcrEngine implementations are deliberately client-agnostic -- callers
pass in an already-constructed client object (see vision_api_engine.py
docstring), so we can't import/catch provider-specific exception types
without hard-requiring that provider's SDK as a dependency.
"""

from __future__ import annotations


class OcrEngineError(Exception):
    """Raised when an OcrEngine fails to produce a result after
    exhausting its retry policy (or for a non-retryable failure)."""

    def __init__(self, engine_name: str, message: str, *, cause: Exception | None = None):
        self.engine_name = engine_name
        self.cause = cause
        super().__init__(f"[{engine_name}] {message}")
