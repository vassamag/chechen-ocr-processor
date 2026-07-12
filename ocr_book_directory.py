"""
ocr_book_directory.py

Runs every image in a directory through OpenAI's Vision API (using
chechen_ocr's existing OpenAIVisionEngine) and writes one combined
.txt file with "[Страница N]" markers, in the same format the manual
ChatGPT-chat workflow has been producing.

Why this instead of the manual chat workflow:
- Each image is one independent API call -- no risk of the model
  "losing focus" on a long prompt over many images in one chat session
  (the exact failure mode found earlier: manual batches of 15+ still
  occasionally fell back to noticeably worse quality).
- No manual copy-pasting of batches or waiting for "продолжай".
- Progress is saved after every single image (see PROGRESS_FILE) --
  if the script crashes, hits a rate limit, or you stop it partway
  through 590 images, re-running it picks up where it left off
  instead of starting over or re-paying for already-done pages.

Usage:
    pip install openai --break-system-packages
    export OPENAI_API_KEY=sk-...      (or pass --api-key)

    python ocr_book_directory.py \
        --images-dir "C:\\Users\\vassa_000\\Desktop\\Ekha_Buisanash_Pages" \
        --output book_ekha_buisanash_vision.txt
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("ocr_book_directory")

PROMPT = (
    "Распознай текст на изображении. Это чеченский текст на кириллице, "
    "содержащий букву палочка (Ӏ, U+04C0), которая визуально похожа на "
    "латинскую I, цифру 1, или на буквы Т/Г, но является отдельной буквой "
    "чеченского алфавита. Обращай особое внимание на различение этих "
    "похожих символов — палочка встречается после согласных г, к, х, т, "
    "ц, ч, д, б, п и образует с ними отдельные буквосочетания "
    "(гӀ, кӀ, хӀ, тӀ и т.д.).\n\n"
    "Если в нижней части страницы виден номер страницы — укажи его "
    "первой строкой в формате: [Страница N]\n"
    "Если номер страницы не виден или неразборчив — укажи: [Страница ?]\n\n"
    "Далее верни распознанный текст, без комментариев, без markdown-разметки, "
    "сохраняя разбивку на строки и абзацы, как на исходном фото."
)

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff"}


def load_progress(progress_file: Path) -> dict[str, str]:
    """filename -> recognized text, for images already done in a prior run."""
    if not progress_file.exists():
        return {}
    return json.loads(progress_file.read_text(encoding="utf-8"))


def save_progress(progress_file: Path, progress: dict[str, str]) -> None:
    progress_file.write_text(json.dumps(progress, ensure_ascii=False, indent=0), encoding="utf-8")


def extract_page_marker(text: str) -> tuple[str, str]:
    """
    Splits the model's leading "[Страница N]" (or "[Страница ?]") line
    off from the rest of the text. Returns (marker_text, remaining_text).
    marker_text is "N" or "?" -- "?" (unrecognized) if no marker line
    was found at all, so downstream tooling always gets a consistent
    shape to work with.
    """
    match = re.match(r"\s*\[Страница\s+(\d+|\?)\]\s*\n?", text)
    if match:
        return match.group(1), text[match.end() :]
    return "?", text


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--images-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--api-key", default=None, help="defaults to OPENAI_API_KEY env var")
    parser.add_argument("--model", default="gpt-4o")
    parser.add_argument(
        "--progress-file",
        default=None,
        type=Path,
        help="defaults to <output>.progress.json next to --output",
    )
    args = parser.parse_args()

    try:
        import openai
    except ImportError:
        logger.error("Missing dependency. Run: pip install openai --break-system-packages")
        return 1

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from chechen_ocr.ocr.vision_api_engine import OpenAIVisionEngine

    images_dir = args.images_dir
    if not images_dir.is_dir():
        logger.error("Not a directory: %s", images_dir)
        return 1

    image_paths = sorted(p for p in images_dir.iterdir() if p.suffix.lower() in IMAGE_EXTENSIONS)
    if not image_paths:
        logger.error("No image files found in %s", images_dir)
        return 1
    logger.info("Found %d images in %s", len(image_paths), images_dir)

    progress_file = args.progress_file or args.output.with_suffix(".progress.json")
    progress = load_progress(progress_file)
    logger.info("Resuming: %d/%d images already done", len(progress), len(image_paths))

    client = openai.OpenAI(api_key=args.api_key)  # falls back to OPENAI_API_KEY env var
    engine = OpenAIVisionEngine(client=client, model=args.model, prompt=PROMPT)

    for i, image_path in enumerate(image_paths, 1):
        if image_path.name in progress:
            continue  # already done in a prior run

        logger.info("[%d/%d] %s", i, len(image_paths), image_path.name)
        try:
            result = engine.recognize(image_path)
        except Exception:
            logger.exception(
                "Failed on %s -- progress so far is saved; re-run this "
                "script to retry this image and continue.",
                image_path.name,
            )
            save_progress(progress_file, progress)
            return 1

        progress[image_path.name] = result.text
        save_progress(progress_file, progress)  # save after every image, not just at the end

    # Assemble the final combined file, using each image's OWN recognized
    # page number (falling back to "?" consistently via extract_page_marker)
    lines = []
    for image_path in image_paths:
        raw_text = progress[image_path.name]
        page_marker, body = extract_page_marker(raw_text)
        lines.append(f"[Страница {page_marker}]")
        lines.append("")
        lines.append(body.strip())
        lines.append("")

    args.output.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Done. Wrote %s (%d images)", args.output, len(image_paths))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
