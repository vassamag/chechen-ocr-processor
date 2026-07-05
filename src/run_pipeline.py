from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

VERSION = "v0.1-txt-gui-pipeline"


def run_command(command: list[str], cwd: Path) -> None:
    print()
    print("RUN:")
    print(" ".join(command))
    print()

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"

    result = subprocess.run(
        command,
        cwd=str(cwd),
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        env=env,
    )

    if result.stdout:
        print(result.stdout)

    if result.stderr:
        print(result.stderr, file=sys.stderr)

    if result.returncode != 0:
        raise RuntimeError(
            f"Command failed with exit code {result.returncode}: {' '.join(command)}"
        )
def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run Chechen OCR TXT post-processing pipeline"
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Input raw OCR TXT file",
    )
    parser.add_argument(
        "--out-dir",
        required=True,
        help="Output folder",
    )
    parser.add_argument(
        "--base-name",
        default="processed",
        help="Base output name without extension. Default: processed",
    )

    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[1]
    src_dir = project_root / "src"

    input_path = Path(args.input).resolve()
    out_dir = Path(args.out_dir).resolve()
    base_name = args.base_name

    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    ensure_dir(out_dir)

    processed_txt = out_dir / f"{base_name}.txt"

    print(f"Chechen OCR TXT Pipeline {VERSION}")
    print(f"Project root: {project_root}")
    print(f"Input TXT: {input_path}")
    print(f"Output folder: {out_dir}")
    print(f"Processed TXT: {processed_txt}")

    # Step 1: main TXT post-processing.
    #
    # process_text.py currently expects process.py to be in the current directory,
    # so we run it from src_dir.
    run_command(
        [
            sys.executable,
            "process_text.py",
            str(input_path),
            "--output",
            str(processed_txt),
        ],
        cwd=src_dir,
    )

    # Step 2: final QA report.
    final_qa_report = out_dir / f"{base_name}_final_qa_report.txt"
    review_csv = out_dir / f"{base_name}_review_placeholder.csv"

    # final_qa_report.py expects a review CSV argument.
    # For the simple TXT GUI version, we create a tiny placeholder CSV.
    if not review_csv.exists():
        review_csv.write_text("decision\n", encoding="utf-8")

    run_command(
        [
            sys.executable,
            "final_qa_report.py",
            "--final",
            str(processed_txt),
            "--review",
            str(review_csv),
            "--out",
            str(final_qa_report),
        ],
        cwd=src_dir,
    )

    # Step 3: suspicious contexts report.
    suspicious_contexts = out_dir / f"{base_name}_remaining_suspicious_contexts.txt"

    run_command(
        [
            sys.executable,
            "extract_remaining_suspicious_contexts.py",
            "--source",
            str(processed_txt),
            "--out",
            str(suspicious_contexts),
        ],
        cwd=src_dir,
    )

    # Step 4: write a small manifest.
    manifest = out_dir / f"{base_name}_manifest.txt"
    manifest.write_text(
        "\n".join(
            [
                f"Chechen OCR TXT Pipeline {VERSION}",
                "",
                f"Input TXT: {input_path}",
                f"Output folder: {out_dir}",
                "",
                "Created files:",
                f"- {processed_txt.name}",
                f"- {base_name}_raw_ocr.txt",
                f"- {base_name}_corrections.txt",
                f"- {base_name}_suspicious.txt",
                f"- {final_qa_report.name}",
                f"- {suspicious_contexts.name}",
                f"- {suspicious_contexts.with_suffix('.csv').name}",
                f"- {manifest.name}",
            ]
        ),
        encoding="utf-8",
    )

    print()
    print("DONE")
    print(f"Output folder: {out_dir}")
    print(f"Manifest: {manifest}")


if __name__ == "__main__":
    main()