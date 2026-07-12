from dataclasses import dataclass

import pytest

from chechen_ocr.ocr.errors import OcrEngineError
from chechen_ocr.ocr.vision_api_engine import OpenAIVisionEngine, extract_usage


@dataclass
class _FakeUsage:
    prompt_tokens: int
    completion_tokens: int


@dataclass
class _FakeMessage:
    content: str


@dataclass
class _FakeChoice:
    message: _FakeMessage


class _FakeResponse:
    def __init__(self, text: str, prompt_tokens: int = 10, completion_tokens: int = 5):
        self.choices = [_FakeChoice(message=_FakeMessage(content=text))]
        self.usage = _FakeUsage(prompt_tokens, completion_tokens)

    def model_dump(self) -> dict:
        return {
            "choices": [{"message": {"content": self.choices[0].message.content}}],
            "usage": {
                "prompt_tokens": self.usage.prompt_tokens,
                "completion_tokens": self.usage.completion_tokens,
            },
        }


class _FakeCompletions:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class _FakeChat:
    def __init__(self, completions):
        self.completions = completions


class _FakeClient:
    def __init__(self, responses):
        self.chat = _FakeChat(_FakeCompletions(responses))


def _make_image(tmp_path):
    path = tmp_path / "page.jpg"
    path.write_bytes(b"\xff\xd8\xff\xe0fake-jpeg-bytes")
    return path


def test_recognize_returns_text_and_usage(tmp_path):
    client = _FakeClient([_FakeResponse("Ӏабо хӀара текст")])
    engine = OpenAIVisionEngine(client=client, model="gpt-4o")

    result = engine.recognize(_make_image(tmp_path))

    assert result.text == "Ӏабо хӀара текст"
    assert result.engine_name == "openai_vision"
    assert result.prompt_tokens == 10
    assert result.completion_tokens == 5
    assert result.raw_response is not None


def test_timeout_is_passed_to_client(tmp_path):
    client = _FakeClient([_FakeResponse("text")])
    engine = OpenAIVisionEngine(client=client, timeout_seconds=42.0)

    engine.recognize(_make_image(tmp_path))

    call_kwargs = client.chat.completions.calls[0]
    assert call_kwargs["timeout"] == 42.0


def test_no_timeout_kwarg_when_disabled(tmp_path):
    client = _FakeClient([_FakeResponse("text")])
    engine = OpenAIVisionEngine(client=client, timeout_seconds=None)

    engine.recognize(_make_image(tmp_path))

    call_kwargs = client.chat.completions.calls[0]
    assert "timeout" not in call_kwargs


def test_retries_on_transient_failure_then_succeeds(tmp_path, monkeypatch):
    monkeypatch.setattr("chechen_ocr.ocr.retry.time.sleep", lambda _: None)
    client = _FakeClient([ConnectionError("transient"), _FakeResponse("recovered text")])
    engine = OpenAIVisionEngine(client=client, max_retries=2)

    result = engine.recognize(_make_image(tmp_path))

    assert result.text == "recovered text"
    assert len(client.chat.completions.calls) == 2


def test_raises_ocr_engine_error_after_exhausting_retries(tmp_path, monkeypatch):
    monkeypatch.setattr("chechen_ocr.ocr.retry.time.sleep", lambda _: None)
    client = _FakeClient([ConnectionError("fail")] * 10)
    engine = OpenAIVisionEngine(client=client, max_retries=2)

    with pytest.raises(OcrEngineError):
        engine.recognize(_make_image(tmp_path))


def test_extract_usage_from_dict_response():
    prompt, completion = extract_usage({"usage": {"prompt_tokens": 7, "completion_tokens": 3}})
    assert (prompt, completion) == (7, 3)


def test_extract_usage_returns_none_on_unexpected_shape():
    prompt, completion = extract_usage("not a response at all")
    assert (prompt, completion) == (None, None)


def test_tiff_extension_gets_correct_mime_type(tmp_path):
    client = _FakeClient([_FakeResponse("text")])
    engine = OpenAIVisionEngine(client=client)

    path = tmp_path / "scan.tiff"
    path.write_bytes(b"fake-tiff-bytes")
    engine.recognize(path)

    call_kwargs = client.chat.completions.calls[0]
    image_url = call_kwargs["messages"][0]["content"][1]["image_url"]["url"]
    assert image_url.startswith("data:image/tiff;base64,")


def test_bmp_extension_gets_correct_mime_type(tmp_path):
    client = _FakeClient([_FakeResponse("text")])
    engine = OpenAIVisionEngine(client=client)

    path = tmp_path / "scan.bmp"
    path.write_bytes(b"fake-bmp-bytes")
    engine.recognize(path)

    call_kwargs = client.chat.completions.calls[0]
    image_url = call_kwargs["messages"][0]["content"][1]["image_url"]["url"]
    assert image_url.startswith("data:image/bmp;base64,")


def test_unknown_extension_raises_instead_of_silently_defaulting(tmp_path):
    client = _FakeClient([_FakeResponse("text")])
    engine = OpenAIVisionEngine(client=client)

    path = tmp_path / "scan.heic"
    path.write_bytes(b"fake-heic-bytes")

    with pytest.raises(ValueError, match="Unsupported image extension"):
        engine.recognize(path)

    # Must fail before ever calling the API -- no wasted call/cost.
    assert len(client.chat.completions.calls) == 0
