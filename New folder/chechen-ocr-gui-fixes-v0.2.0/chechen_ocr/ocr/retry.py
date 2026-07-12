"""
retry.py

A small, provider-agnostic retry-with-exponential-backoff helper for
OcrEngine implementations that call a remote API (network errors, rate
limits, and transient 5xx responses are all common and usually worth
retrying; a bad request or bad auth is not).

Deliberately does not try to special-case specific exception types
(e.g. openai.RateLimitError) since OcrEngine implementations accept an
arbitrary, already-constructed client (see vision_api_engine.py) and
we don't want to hard-require any particular provider SDK just to
catch its exception classes. This is a real limitation: without
knowing the specific exception type, we can't tell a genuinely
non-retryable error (bad API key, malformed request) from a transient
one, so we retry broadly and rely on max_retries to bound the cost of
retrying something that will never succeed. If you need smarter
handling (e.g. respecting a Retry-After header), wrap your client call
in retry_with_backoff's `is_retryable` hook.
"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from typing import TypeVar

from .errors import OcrEngineError

logger = logging.getLogger(__name__)

T = TypeVar("T")


def retry_with_backoff(
    fn: Callable[[], T],
    *,
    engine_name: str,
    max_retries: int = 3,
    base_delay_seconds: float = 1.0,
    max_delay_seconds: float = 30.0,
    is_retryable: Callable[[Exception], bool] | None = None,
) -> T:
    """
    Calls `fn()`, retrying on exception with exponential backoff + jitter.

    - max_retries=3 means up to 4 total attempts (1 initial + 3 retries).
    - Delay doubles each attempt, capped at max_delay_seconds, with up
      to 25% random jitter added to avoid a thundering-herd retry
      pattern if many pages are being processed concurrently.
    - is_retryable(exc), if given, lets a caller opt out of retrying
      exceptions it recognizes as non-transient (e.g. an auth error).
      Defaults to "retry everything" (see module docstring for why).
    - Raises OcrEngineError (chaining the last underlying exception)
      once retries are exhausted.
    """
    last_exc: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 -- see module docstring
            last_exc = exc

            if is_retryable is not None and not is_retryable(exc):
                logger.error("%s: non-retryable error: %s", engine_name, exc)
                raise OcrEngineError(engine_name, f"non-retryable error: {exc}", cause=exc) from exc

            if attempt == max_retries:
                break

            delay = min(base_delay_seconds * (2**attempt), max_delay_seconds)
            delay += random.uniform(0, delay * 0.25)
            logger.warning(
                "%s: attempt %d/%d failed (%s); retrying in %.1fs",
                engine_name,
                attempt + 1,
                max_retries + 1,
                exc,
                delay,
            )
            time.sleep(delay)

    raise OcrEngineError(
        engine_name,
        f"failed after {max_retries + 1} attempts: {last_exc}",
        cause=last_exc,
    ) from last_exc
