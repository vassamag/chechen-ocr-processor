"""
processing.py

Tkinter widgets must only ever be touched from the main thread, but
OCR/PDF rasterization/correction can take seconds to minutes. This
module runs that work in a background daemon thread and communicates
back to the main thread via a queue.Queue, which the GUI polls
periodically with `root.after(...)` -- the standard safe pattern for
mixing Tkinter with background work.

Deliberately has no Tkinter import, so it's testable without a
display.
"""

from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass
class LogMessage:
    level: int
    text: str


@dataclass
class JobDone:
    result: Any = None
    error: Exception | None = None


class QueueLogHandler(logging.Handler):
    """Logging handler that pushes formatted records into a queue.Queue
    instead of writing anywhere directly -- lets the GUI show live
    progress (reusing chechen_ocr's existing INFO/WARNING logging,
    see processor.py) without touching widgets from a background
    thread."""

    def __init__(self, message_queue: queue.Queue[Any]):
        super().__init__()
        self._queue = message_queue

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
        except Exception:
            msg = record.getMessage()
        self._queue.put(LogMessage(level=record.levelno, text=msg))


def run_in_background(
    target: Callable[[], Any],
    message_queue: queue.Queue[Any],
) -> threading.Thread:
    """
    Runs `target()` in a daemon thread. Puts exactly one JobDone(...)
    onto message_queue when finished -- `result=...` on success,
    `error=...` (the caught exception) on failure. Never raises in the
    background thread; the caller is expected to poll message_queue
    and re-raise/display the error on the main thread if present.
    """

    def runner() -> None:
        try:
            result = target()
            message_queue.put(JobDone(result=result))
        except Exception as exc:  # noqa: BLE001 -- surfaced to the GUI, not swallowed
            message_queue.put(JobDone(error=exc))

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    return thread
