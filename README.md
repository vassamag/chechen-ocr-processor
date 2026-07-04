# Chechen OCR Processor

Chechen OCR post-processing toolkit.

This project contains Python scripts and rule dictionaries for cleaning OCR output of Chechen Cyrillic text.

The processor focuses on:

- Chechen Cyrillic OCR cleanup
- palochka normalization: `Ӏ`
- detection of suspicious OCR characters
- review table generation
- final QA reports
- comparison against manually corrected DOCX files

## Current stable status

Current technical version:

`OCR_PROCESSOR_V5_4`

Final safe output in the working local project:

`output/recognized_text_ordered_chechen_fixed_reviewed_final_v4.txt`

The final output file itself is not included in this repository.

## Main pipeline

```text
process.py
→ make_review_table_with_context.py
→ prefill_review_from_manual_docx.py
→ apply_review_table.py
→ normalize_palochka_final.py
→ final_qa_report.py
→ extract_remaining_suspicious_contexts.py
→ normalize_remaining_ocr_chars_v2.py
→ final_qa_report.py
→ extract_remaining_suspicious_contexts.py
```

## Repository contents

```text
src/      Python scripts
rules/    Chechen OCR correction dictionaries and phrase lists
docs/     Technical notes and status reports
examples/ Placeholder examples
tests/    Placeholder for future tests
```

## Data policy

This repository does not include:

- scanned book pages
- copyrighted source texts
- DOCX books
- generated OCR outputs
- local `input/` or `output/` folders

Those files must stay outside GitHub.

## Notes

The repository contains only the processor code, rule dictionaries, and technical documentation.

The working OCR data, scanned images, manually corrected DOCX files, and generated outputs are intentionally excluded.