"""
config.py

Central place for anything environment-specific: paths to rule files,
Tesseract binary location, default language, output directory.

Replaces the hardcoded `C:\\Program Files\\Tesseract-OCR\\tesseract.exe`
and the "rules/ relative to current working directory" assumptions
that existed in the original scripts.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

try:
    import tomllib  # type: ignore[import-not-found]  # Python 3.11+; see note below
    # mypy is configured for our minimum supported version (3.10),
    # which doesn't ship this module -- the ignore above is expected
    # and correct, not a suppressed real error.
except ImportError:  # pragma: no cover
    tomllib = None  # type: ignore[assignment]


PACKAGE_ROOT = Path(__file__).resolve().parent
DEFAULT_RULES_DIR = PACKAGE_ROOT.parent / "rules"


@dataclass(frozen=True)
class Settings:
    rules_dir: Path = DEFAULT_RULES_DIR
    output_dir: Path = Path("output")

    # OCR-related. None means "let the engine/library decide"
    # (e.g. pytesseract will look up tesseract on PATH).
    tesseract_cmd: str | None = None
    default_lang: str = "rus"

    # OpenAI-Vision-style engine config (optional, only used if that
    # engine is selected).
    vision_model: str = "gpt-4o"
    vision_prompt: str | None = None

    # If a processed document's suspicious-word ratio exceeds this
    # fraction of its total words, process_text() logs a WARNING (see
    # processor.py) -- a cheap, automatic signal that a particular page
    # was likely a poor scan, worth flagging before a human review
    # queue builds up silently. Purely a logging threshold; it does not
    # change any correction behavior.
    suspicious_ratio_warning_threshold: float = 0.05

    # File-handling safety limits (see security.py). Defaults are
    # generous for a single book chapter/page but bounded, since DOCX
    # and PDF are compound/archive formats that shouldn't be trusted
    # unconditionally once input can come from someone other than the
    # project owner.
    max_docx_file_size_bytes: int = 50 * 1024 * 1024  # 50 MB
    max_docx_uncompressed_size_bytes: int = 500 * 1024 * 1024  # 500 MB
    max_docx_compression_ratio: float = 100.0
    max_docx_zip_entry_count: int = 2000
    max_pdf_file_size_bytes: int = 200 * 1024 * 1024  # 200 MB
    max_pdf_pages: int = 500
    pdf_render_timeout_seconds: int = 300

    @classmethod
    def default(cls) -> Settings:
        return cls()

    @classmethod
    def from_file(cls, path: Path) -> Settings:
        """
        Loads settings from a TOML file, e.g.:

            rules_dir = "rules"
            output_dir = "output"
            tesseract_cmd = "/usr/bin/tesseract"
            default_lang = "rus"
            vision_model = "gpt-4o"

        Unspecified keys fall back to defaults.
        """
        if tomllib is None:
            raise RuntimeError(
                "tomllib is not available (Python < 3.11); "
                "install 'tomli' and adapt this loader, or construct "
                "Settings(...) directly."
            )

        path = Path(path)
        with path.open("rb") as f:
            data = tomllib.load(f)

        base_dir = path.parent

        def resolve(key: str, default: Path) -> Path:
            value = data.get(key)
            return (base_dir / value) if value else default

        return cls(
            rules_dir=resolve("rules_dir", DEFAULT_RULES_DIR),
            output_dir=resolve("output_dir", Path("output")),
            tesseract_cmd=data.get("tesseract_cmd"),
            default_lang=data.get("default_lang", "rus"),
            vision_model=data.get("vision_model", "gpt-4o"),
            vision_prompt=data.get("vision_prompt"),
        )
