"""
Vision-API-based OCR engine (e.g. OpenAI GPT-4o/GPT-4V-style multimodal
chat completion endpoints).

This engine is deliberately decoupled from any specific SDK: it takes
an already-constructed `client` object (e.g. `openai.OpenAI(...)`) and
only assumes it exposes `client.chat.completions.create(...)` with the
OpenAI wire format. Swapping in Anthropic/Google/etc. means writing a
small adapter with the same `recognize()` signature -- the Pipeline
and ChechenOcrProcessor code does not change.

Note on correction pipeline interaction: Vision-API engines tend to
"read" the word semantically rather than misrendering individual
glyphs, so they rarely produce the Latin-lookalike artifacts that
DirectPalochkaLookalikes / PatternBasedPalochka / CommonWordFixList
target. See processor.build_pipeline(), which disables those
correctors when ocr_engine_name != "tesseract". They can, however,
"hallucinate" plausible-but-wrong words -- that failure mode is not
covered by this pipeline and would need a separate corrector/reviewer
step if it becomes a real problem in practice.

Robustness notes (see ocr/retry.py for details):
- Network errors, rate limits, and transient 5xx responses are common
  for any API-based engine over a batch of many pages. recognize()
  retries with exponential backoff + jitter by default.
- A per-call timeout is passed through to the client if it accepts a
  `timeout=` kwarg (the OpenAI SDK does); engines using a client that
  doesn't support this should configure timeouts on the client itself.
- Every response's raw payload is kept on OcrResult.raw_response for
  audit -- useful when a page comes back looking "hallucinated" and
  you want to see exactly what the API returned, not just the final
  text. Combine with prompt/completion token counts (best-effort, via
  extract_usage) if you need to track spend across a batch.
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Any

from .base import OcrResult
from .retry import retry_with_backoff

logger = logging.getLogger(__name__)

DEFAULT_PROMPT = (
    "Распознай текст на изображении. Это чеченский текст на кириллице, "
    "содержащий букву палочка (Ӏ, U+04C0), которая визуально похожа на "
    "латинскую I или цифру 1, но является отдельной буквой. Верни только "
    "распознанный текст, без комментариев, без markdown-разметки."
)

_EXT_TO_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
}


def _mime_for(image_path: Path) -> str:
    suffix = image_path.suffix.lower()
    mime = _EXT_TO_MIME.get(suffix)
    if mime is None:
        raise ValueError(
            f"Unsupported image extension '{suffix}' for {image_path.name}. "
            f"Supported: {', '.join(sorted(_EXT_TO_MIME))}. "
            "Silently defaulting to image/png here would send the wrong "
            "Content-Type for the actual bytes -- convert the file first "
            "if you need a format outside this list."
        )
    return mime


def extract_usage(raw_response: Any) -> tuple[int | None, int | None]:
    """
    Best-effort extraction of (prompt_tokens, completion_tokens) from
    an OpenAI-compatible chat completion response (either the SDK
    object or its .model_dump() dict form). Returns (None, None) if
    the shape doesn't match what's expected -- this is intentionally
    forgiving, since usage reporting is a nice-to-have, not something
    that should ever break a call that otherwise succeeded.
    """
    try:
        if isinstance(raw_response, dict):
            usage = raw_response.get("usage") or {}
            return usage.get("prompt_tokens"), usage.get("completion_tokens")
        usage = getattr(raw_response, "usage", None)
        if usage is None:
            return None, None
        return (
            getattr(usage, "prompt_tokens", None),
            getattr(usage, "completion_tokens", None),
        )
    except Exception:  # noqa: BLE001 -- usage extraction must never break a call
        logger.debug("could not extract token usage from response", exc_info=True)
        return None, None


class OpenAIVisionEngine:
    name = "openai_vision"

    def __init__(
        self,
        client: Any,
        model: str = "gpt-4o",
        prompt: str | None = None,
        timeout_seconds: float | None = 60.0,
        max_retries: int = 3,
    ):
        self.client = client
        self.model = model
        self.prompt = prompt or DEFAULT_PROMPT
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries

    def recognize(self, image_path: Path, lang: str = "che") -> OcrResult:
        image_path = Path(image_path)
        mime = _mime_for(image_path)
        image_b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")

        def call() -> Any:
            kwargs: dict[str, Any] = {
                "model": self.model,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": self.prompt},
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:{mime};base64,{image_b64}"},
                            },
                        ],
                    }
                ],
            }
            if self.timeout_seconds is not None:
                kwargs["timeout"] = self.timeout_seconds
            return self.client.chat.completions.create(**kwargs)

        logger.debug("calling %s (model=%s) for %s", self.name, self.model, image_path)

        response = retry_with_backoff(
            call,
            engine_name=self.name,
            max_retries=self.max_retries,
        )

        text = response.choices[0].message.content or ""
        raw = response.model_dump() if hasattr(response, "model_dump") else None
        prompt_tokens, completion_tokens = extract_usage(raw if raw is not None else response)

        logger.info(
            "%s recognized %d chars from %s (prompt_tokens=%s, completion_tokens=%s)",
            self.name,
            len(text),
            image_path.name,
            prompt_tokens,
            completion_tokens,
        )

        return OcrResult(
            text=text,
            engine_name=self.name,
            raw_response=raw,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
