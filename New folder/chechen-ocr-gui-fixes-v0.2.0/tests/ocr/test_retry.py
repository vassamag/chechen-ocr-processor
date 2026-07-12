import pytest

from chechen_ocr.ocr.errors import OcrEngineError
from chechen_ocr.ocr.retry import retry_with_backoff


def test_succeeds_immediately_without_retrying():
    calls = []

    def fn():
        calls.append(1)
        return "ok"

    result = retry_with_backoff(fn, engine_name="test", max_retries=3, base_delay_seconds=0)

    assert result == "ok"
    assert len(calls) == 1


def test_retries_then_succeeds(monkeypatch):
    monkeypatch.setattr("chechen_ocr.ocr.retry.time.sleep", lambda _: None)
    calls = []

    def fn():
        calls.append(1)
        if len(calls) < 3:
            raise ConnectionError("transient")
        return "ok"

    result = retry_with_backoff(fn, engine_name="test", max_retries=5, base_delay_seconds=0)

    assert result == "ok"
    assert len(calls) == 3


def test_raises_ocr_engine_error_after_exhausting_retries(monkeypatch):
    monkeypatch.setattr("chechen_ocr.ocr.retry.time.sleep", lambda _: None)
    calls = []

    def fn():
        calls.append(1)
        raise ConnectionError("always fails")

    with pytest.raises(OcrEngineError) as excinfo:
        retry_with_backoff(fn, engine_name="test-engine", max_retries=2, base_delay_seconds=0)

    assert len(calls) == 3  # 1 initial + 2 retries
    assert "test-engine" in str(excinfo.value)
    assert isinstance(excinfo.value.cause, ConnectionError)


def test_is_retryable_hook_can_reject_immediately(monkeypatch):
    monkeypatch.setattr("chechen_ocr.ocr.retry.time.sleep", lambda _: None)
    calls = []

    def fn():
        calls.append(1)
        raise ValueError("bad api key")

    with pytest.raises(OcrEngineError) as excinfo:
        retry_with_backoff(
            fn,
            engine_name="test",
            max_retries=5,
            base_delay_seconds=0,
            is_retryable=lambda exc: not isinstance(exc, ValueError),
        )

    # Should not have retried at all -- ValueError is treated as non-retryable.
    assert len(calls) == 1
    assert "non-retryable" in str(excinfo.value)
