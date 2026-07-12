# chechen-ocr

Chechen OCR post-processing toolkit, built around two small,
composable abstractions:

- **`OcrEngine`** — turns an image into raw text (Tesseract, an
  OpenAI-Vision-style multimodal API, or anything else you adapt).
- **`Corrector` / `Pipeline`** — turns raw text into corrected text
  plus a structured change log, one small testable step at a time.

`ChechenOcrProcessor` ties the two together and is the only class most
callers need.

> **Note on versioning:** this repository starts at `0.1.0` rather
> than continuing an older, informal numbering scheme used during
> earlier development (a separate, unstructured script collection that
> predates this Corrector/Pipeline architecture — see
> [`vassamag/chechen-ocr-processor`'s earlier history](https://github.com/vassamag/chechen-ocr-processor),
> now superseded). Versions `0.x.y` mean active development, where the
> public API may still change; `1.0.0` will mark the first release
> considered stable.

## Quick start

```python
from pathlib import Path
from chechen_ocr import ChechenOcrProcessor, Settings
from chechen_ocr.ocr import TesseractEngine

processor = ChechenOcrProcessor(
    settings=Settings.default(),
    ocr_engine=TesseractEngine(tesseract_cmd=None),  # None -> use PATH
)

doc = processor.process_image(Path("page001.jpg"))
print(doc.corrected_text)
print(len(doc.corrections), "automatic corrections")
print(len(doc.suspicious), "words flagged for human review")

processor.export_suspicious_csv(doc, Path("output/page001_review.csv"))
```

Already have OCR text (e.g. from a batch scan) and just want the
Chechen-specific cleanup?

```python
doc = processor.process_text(raw_text)
```

### Using a Vision-API engine instead of Tesseract

```python
from openai import OpenAI
from chechen_ocr.ocr import OpenAIVisionEngine

processor = ChechenOcrProcessor(
    settings=Settings.default(),
    ocr_engine=OpenAIVisionEngine(client=OpenAI(), model="gpt-4o"),
)
doc = processor.process_image(Path("page001.jpg"))
```

`ChechenOcrProcessor` automatically builds a pipeline appropriate for
the engine that produced the text (`build_pipeline()` in
`processor.py`): Tesseract-specific Latin-lookalike correctors
(`palochka_direct`, `palochka_pattern`, `common_word_fix`) are skipped
for non-Tesseract engines, since those artifacts are specific to how
Tesseract renders a mis-recognized glyph.

## Human review workflow

```python
doc = processor.process_text(raw_text)

# Export a context-rich CSV for a human reviewer (columns match the
# original make_review_table_with_context.py output):
processor.export_review_table_csv(doc, Path("review.csv"))

# ... a person fills in `decision` ("replace"/"reject"/"pending") and
# `replacement` columns in review.csv ...

new_text, results = processor.apply_review_table_csv(doc, Path("review.csv"))
```

`apply_review_table_csv` only ever applies rows with `decision ==
"replace"` and a non-empty `replacement`. By default it requires the
row's `corrected_context` snippet to match verbatim in the text (so it
never risks replacing the wrong occurrence of a common word);
`allow_word_fallback=True` additionally allows replacing a bare word
when it's unique in the whole text.

## DOCX input/output

```python
doc = processor.process_docx(Path("scanned_output.docx"))   # plain-text extraction, then correction
processor.export_docx(doc, Path("corrected.docx"))            # suspicious words highlighted yellow
```

CLI equivalents: `chechen-ocr-text input.docx --output out --docx-output`
and `chechen-ocr-apply-review corrected.txt review.csv --output final.txt`.

## Desktop GUI

```bash
pip install -e ".[tesseract]"   # tkinter itself is stdlib; needs the system Tk package
                                  # (apt install python3-tk / brew installs it with python)
chechen-ocr-gui
```

Open a file (image/PDF/TXT/DOCX) or a whole directory (batch mode),
click Process, review flagged words directly in the table (edit
`decision`/`replacement` inline, no CSV round-trip required), then
export the corrected TXT, a highlighted DOCX, or the review CSV.
Processing runs in a background thread so the UI never freezes; the
Log tab shows the same INFO/WARNING messages `ChechenOcrProcessor`
already logs (see "Logging and quality metrics" below).

A "Source" selector in the toolbar (Scan/Tesseract vs Pre-recognized/
Vision) picks which correction rules apply — Tesseract-lookalike
patterns for the former, case-normalization rules for the latter.
It never triggers OCR itself; Vision recognition is expected to
happen elsewhere (see `ocr_book_directory.py`-style scripts) and this
app just corrects text you already have, same as `process_text()`'s
`ocr_engine_name` argument directly. No TTS/translation
integration — considered and explicitly deferred; see project
discussion. A web version (Streamlit) is a plausible later addition
sharing this same `chechen_ocr` API — the GUI holds no business logic
itself, only presentation, so that stays possible without duplicating
anything.

`tests/gui/test_gui_integration.py` drives the real Tkinter app
end-to-end and needs an actual display; it skips gracefully in a
headless environment without one. Run explicitly with:

```bash
xvfb-run -a pytest tests/gui/ -v -m gui   # Linux CI/headless
pytest tests/gui/ -v -m gui                # if you have a real display
```

## Batch processing (a whole book, not one file at a time)

```python
from chechen_ocr import ChechenOcrProcessor, Settings, BatchProcessor
from chechen_ocr.ocr import TesseractEngine

processor = ChechenOcrProcessor(settings=Settings.default(), ocr_engine=TesseractEngine())
batch = BatchProcessor(processor)

result = batch.process_directory(Path("scans/"))  # any mix of .jpg/.png/.tiff/.pdf/.txt/.docx
paths = batch.export(result, Path("output/"), base_name="book")

result.metrics.total_words, result.metrics.suspicious_ratio  # whole-book totals
result.worst_files[:5]  # per-file breakdown, worst suspicious-ratio first -- review these first
```

Every input file's raw text (OCR for images/PDF pages, direct read for
TXT, extraction for DOCX) is wrapped in the same `"===== Страница N |
<filename> ====="` service header the rest of the package already
protects from correction and parses for page attribution — all files
are concatenated into one document and run through
`process_text()` exactly once, so correction/suspicious-detection/metrics
behave identically to processing one giant file (no separate
per-file merge logic to keep in sync). Page numbers here are just
each file's position in the sorted list, not a recognized printed
page number — see `batch.py`'s docstring for why that's out of scope.

CLI: `chechen-ocr-batch scans/ --output-dir output/ --base-name book`
prints the worst-ranked files directly, so you can see at a glance
which pages need review first without opening any output file.

## Input/output format support

| Format | Input | Output |
|---|---|---|
| TXT | ✅ `process_text()` | ✅ `doc.corrected_text` |
| DOCX | ✅ `process_docx()` | ✅ `export_docx()` (suspicious words highlighted) |
| JPG/PNG/TIFF/BMP/GIF | ✅ `process_image()` | — |
| PDF (scanned) | ✅ `process_pdf()` | — |
| PDF (output) | — | Not supported — export DOCX and convert externally (e.g. `soffice --headless --convert-to pdf`) if you need one; this project's documents are usually still being reviewed/edited, and PDF is a dead end for that workflow. |

```python
processor = ChechenOcrProcessor(settings=Settings.default(), ocr_engine=TesseractEngine())
doc = processor.process_pdf(Path("scanned_book.pdf"), dpi=300)  # requires the 'pdf' extra
```

`process_pdf` always rasterizes every page and runs it through
whichever `OcrEngine` is configured — it does **not** try to detect or
extract an existing PDF text layer. For this project's actual input
(phone photos of a book, sometimes bundled into a PDF by a scanning
app instead of kept as separate JPGs), a PDF with an already-correct
text layer essentially never occurs — if it did, the whole correction
pipeline wouldn't be needed. Requires the `pdf2image` package (`pip
install -e ".[pdf]"`) plus system `poppler-utils` (`apt install
poppler-utils` / `brew install poppler`).

`OpenAIVisionEngine` also had a silent bug fixed here: unknown image
extensions used to default to `image/png` regardless of actual format
(so e.g. a `.tiff` scan would be sent with the wrong `Content-Type`).
It now recognizes `.png/.jpg/.jpeg/.webp/.gif/.bmp/.tif/.tiff` and
raises `ValueError` immediately (before any API call) for anything
else, instead of silently mislabeling the request.

## Vision-API engine robustness

`OpenAIVisionEngine` retries transient failures (network errors, rate
limits, 5xx responses) with exponential backoff + jitter by default
(`max_retries=3`), and passes a per-call `timeout_seconds` (default 60s)
to the client if it accepts one:

```python
engine = OpenAIVisionEngine(
    client=OpenAI(),
    model="gpt-4o",
    timeout_seconds=60.0,
    max_retries=3,
)
```

All failures raise `chechen_ocr.ocr.OcrEngineError` (wrapping the
underlying exception in `.cause`) once retries are exhausted, so batch
jobs can catch one exception type regardless of which engine is in
use. `TesseractEngine` raises the same error type for setup/image
problems (missing binary, corrupt image), even though it doesn't
retry (a local failure is rarely transient).

Every `OcrResult` keeps the full raw API response (`.raw_response`) and,
best-effort, token counts (`.prompt_tokens` / `.completion_tokens`) for
auditing a page that came back looking hallucinated, or for tracking
spend across a batch:

```python
result = engine.recognize(Path("page.jpg"))
result.raw_response       # full API payload
result.prompt_tokens, result.completion_tokens
```

Known limitation: since `OcrEngine` implementations accept an
arbitrary, already-constructed client (not a specific SDK), the retry
logic can't distinguish a genuinely non-retryable error (bad API key)
from a transient one by exception type — it retries broadly and relies
on `max_retries` to bound wasted calls. Pass `is_retryable=...` to
`ocr.retry.retry_with_backoff` directly if you need smarter handling
for your specific client.

## Logging and quality metrics

`ChechenOcrProcessor.process_text`/`process_image` log to the standard
`logging` module (logger name `chechen_ocr.processor`, nested under
`chechen_ocr`) instead of printing — configure it the normal way:

```python
import logging
logging.basicConfig(level=logging.INFO)  # or configure handlers/formatters as usual
```

Every call logs an INFO summary (`processed N words: M corrections
(<breakdown by rule>), K suspicious (X.X%)`), and a WARNING if the
suspicious-word ratio exceeds `Settings.suspicious_ratio_warning_threshold`
(default 5%) — a cheap signal that a particular page is likely a poor
scan, worth prioritizing for human review before a backlog builds up
silently across a large batch job.

For programmatic monitoring (e.g. aggregating quality across hundreds
of pages), use `compute_metrics`:

```python
metrics = processor.compute_metrics(doc)
metrics.total_words
metrics.corrections_by_rule        # {"palochka_direct": 12, "common_word_fix": 3, ...}
metrics.suspicious_ratio
metrics.unconverted_lookalike_count  # words still containing an unconverted OCR lookalike char
```

## Data-driven fix tables (rules/*.yaml)

`rules/common_word_fixes.yaml` and `rules/known_suspicious_candidates.yaml`
hold the hand-curated whole-word OCR fixes and known-ambiguous-word
candidates respectively — previously hardcoded Python dicts in
`correctors/common_words.py` / `suspicious.py`. Adding a new verified
fix is now a data change, not a code change:

```yaml
# rules/common_word_fixes.yaml
fixes:
  хТара: хӀара
  # ... add a new verified (before -> after) pair here
```

`Dictionaries.load(rules_dir)` reads these at startup (cached per
`rules_dir`). If a rules_dir doesn't have these files (e.g. an older
copy), it falls back to the built-in Python defaults — adding the YAML
files is purely additive, never a hard requirement. A custom
`rules_dir` (e.g. for a different book/dialect) can ship its own
versions of these files without touching any code:

```python
processor = ChechenOcrProcessor(settings=Settings(rules_dir=Path("my_rules")))
```

## Package layout

```
chechen_ocr/
  config.py           Settings (paths, tesseract_cmd, vision model, ...)
  dictionaries.py      Dictionaries.load() — loads rules/*.txt once, cached
  core.py              Correction, CorrectionResult, Corrector protocol, Pipeline
  suspicious.py        detect_suspicious_words() — flags remaining ambiguity
  processor.py         ChechenOcrProcessor (the public API) + build_pipeline()
  cli.py               argparse entrypoints (chechen-ocr-text / -image / -apply-review)
  correctors/
    palochka_direct.py     direct Unicode lookalike -> Ӏ  (highest confidence)
    palochka_pattern.py    consonant + Latin-lookalike -> consonant + Ӏ
    common_words.py        hand-curated whole-word fixes (data, not logic)
    dictionary_candidate.py "exactly one dictionary-valid candidate" disambiguation
    phrase_disambiguation.py context-based tiebreak for ambiguous palochka candidates
    remaining_chars.py      cautious final pass for !, ], Ї/ї
    general_word_fix.py     non-palochka Cyrillic letter-confusion fix (ъ/ь, а/з, ...)
    word_segmentation.py    merged-word splitter -- NOT in default pipeline, see below
  ocr/
    base.py             OcrEngine protocol, OcrResult
    tesseract_engine.py  TesseractEngine
    vision_api_engine.py OpenAIVisionEngine
  review/
    schema.py            ReviewRow, page-index helpers
    build_review_table.py  builds context-rich rows from raw+corrected text
    apply_review_table.py  applies human decisions back onto text
  io/
    docx_reader.py        plain-text extraction from DOCX
    docx_writer.py         DOCX output with suspicious-word highlighting
rules/                  Same dictionaries as the original repo
                         (palochka_words.txt, chechen_words.txt, chechen_phrases.txt)
                         plus common_word_fixes.yaml and
                         known_suspicious_candidates.yaml (see below)
tests/                  Unit tests per corrector/module, using tiny synthetic
                         dictionaries (not the full 80k-word list) so they
                         stay fast and independent of rules/ content.
tests/golden/           Regression test against real, manually-proofread
                         book pages (see "Golden-file regression test" below).
```

## What changed vs. the original script collection

- No module-level globals (`CORRECTION_LOG`, `SUSPICIOUS_LOG`,
  `PALOCHKA_DICTIONARY`) — everything is passed explicitly via
  `PipelineContext` and returned via `CorrectionResult`.
- No hardcoded `C:\Program Files\Tesseract-OCR\tesseract.exe` — path
  comes from `Settings.tesseract_cmd`, defaults to PATH lookup.
- No `importlib.util.spec_from_file_location` hack to reuse
  `process.py` from a sibling script — normal `import chechen_ocr`.
- Fixed an indentation bug in the original `generate_palochka_candidates`
  where the pair-replacement dict was accidentally rebuilt inside an
  unrelated loop (harmless in practice, but confusing and wasteful).
  See `correctors/dictionary_candidate.py` docstring.
- Every correction step is independently unit-tested against tiny,
  synthetic dictionaries (see `tests/conftest.py`), instead of only
  being verified against the full corpus via end-to-end QA reports.
- The review-table workflow (`make_review_table_with_context.py`,
  `apply_review_table.py`) and DOCX I/O (`run_pipeline.py`'s DOCX
  extraction, `process.py`'s highlighted DOCX export) are now part of
  the package (`chechen_ocr.review`, `chechen_ocr.io`) instead of
  standalone scripts, with unit tests covering the context-matching
  and safety-fallback logic.
- `COMMON_WORD_FIXES` (73 hand-verified word pairs) and
  `KNOWN_SUSPICIOUS_CANDIDATES`/whitelist (previously hardcoded
  Python dicts) now live in `rules/common_word_fixes.yaml` and
  `rules/known_suspicious_candidates.yaml`. The Python constants
  remain only as built-in fallback defaults for rules_dir directories
  that don't have these files yet.

## Not yet ported

`compare_docx_vs_v54_*.py` and the various `analyze_reports.py` /
`final_qa_report.py` / `classify_v54_unknown_chunks.py` one-off
analysis scripts were out of scope for this pass — they were mostly
used to produce the original project's manual QA reports during the
initial correction run, and the golden-file regression test
(`tests/golden/`) now serves an equivalent, automated purpose for
ongoing development.

## CI / local development

```bash
pip install -e ".[dev,tesseract,docx,pdf]"

ruff check .            # lint
ruff format --check .   # formatting
mypy chechen_ocr/        # type-check
pytest tests/ -v         # unit tests (golden-file test excluded by default)
pytest tests/golden/ -v -m golden   # golden-file regression -- run manually, see below
```

`pre-commit install` sets up the same lint/format/type/unit-test checks
to run automatically before each commit (`.pre-commit-config.yaml`).

GitHub Actions (`.github/workflows/ci.yml`) runs lint/format/type/unit
tests across Python 3.10/3.11/3.12 on every push/PR.

**Golden-file regression is intentionally not run in CI.** It needs
the actual book text (raw OCR dump + manually-proofread DOCX), which
is excluded from this repo per the project's data policy (see
`tests/golden/data/.gitignore`) and only exists locally. For a
single-maintainer project, standing up private cloud storage (or a
private data repo) just to automate one test wasn't judged worth it --
run `pytest tests/golden/ -v -m golden` manually before merging a
change that touches the correction pipeline. Revisit this decision if
more contributors join.


## File-handling safety (DOCX/PDF)

DOCX and PDF are both compound/archive formats -- once input can come
from someone other than the project owner, they shouldn't be trusted
unconditionally. `chechen_ocr/security.py` adds two checks, both
running before the expensive/risky parsing step:

- **DOCX zip-bomb protection**: a DOCX is a ZIP archive. Before
  `python-docx` decompresses anything, `check_docx_zip_safety()`
  inspects the archive's central directory (sizes only, no
  decompression) and rejects the file if any entry's compression ratio
  or the total uncompressed size looks like a bomb, or if the entry
  count is implausible for a real document.
- **PDF size/page limits + render timeout**: `check_pdf_safety()`
  checks file size and page count via `pdf2image.pdfinfo_from_path`
  (metadata only, no page is rendered) before rasterizing, and the
  actual rasterization call is bounded by
  `Settings.pdf_render_timeout_seconds`.

All limits are configurable via `Settings` (`max_docx_file_size_bytes`,
`max_docx_uncompressed_size_bytes`, `max_docx_compression_ratio`,
`max_docx_zip_entry_count`, `max_pdf_file_size_bytes`, `max_pdf_pages`,
`pdf_render_timeout_seconds`) with generous-but-bounded defaults; a
failing check raises `chechen_ocr.security.UnsafeFileError` before any
parsing happens. `BatchProcessor.process_directory()` already treats
any read failure (including this one) as "skip this file," so a bad
file in a batch doesn't abort the whole run by default.

## Using chechen_words.txt and chechen_phrases.txt

Two general-purpose dictionaries were loaded but unused in earlier
versions of this package. They now power two correctors, plus one
experiment that was found harmful and excluded on purpose:

- **`GeneralWordFix`** (in the default pipeline) — fixes non-palochka
  Cyrillic letter confusions (ъ/ь, а/з, ha/kha) using `chechen_words.txt`
  as the validation dictionary, with the same "exactly one valid
  candidate" conservatism as the palochka correctors. Verified safe
  and slightly beneficial on the golden-file corpus.
- **`PhraseBigramDisambiguator`** (in the default pipeline) — when
  `SingleCandidateDictionaryFix` finds 2+ dictionary-valid palochka
  candidates for a word (and therefore, correctly, leaves it alone),
  this checks whether either candidate forms a real word-bigram (with
  its left/right neighbor) against an index built from
  `chechen_phrases.txt`. On this project's golden-file corpus it fired
  zero times — `chechen_phrases.txt` turns out to be from an unrelated
  book (looks like a religious/Ezekiel-style translation), so bigram
  overlap with this specific novel's ambiguous words is essentially
  nil. Harmless either way; kept since it could help with a different
  book or a more topically-matched phrase corpus.
- **`WordSegmentationFix`** (**not** in the default pipeline) — splits
  merged/no-space OCR tokens (e.g. "боцушэрнаарахь" ->
  "боцуш эрна арахь") by checking whether a token fully decomposes
  into known `chechen_words.txt` entries. Golden-file testing found
  this **net harmful**: Chechen's agglutinative morphology means a
  real word simply missing from a 75k-word dictionary can
  coincidentally decompose into two other, unrelated valid words (e.g.
  "сапаргӀатваьккхира", one real word, got wrongly split). This
  dropped overall similarity from ~92.3% to ~83.8% (worse after
  tightening thresholds, ~91.0%, but still a regression) — a case
  where the golden-file harness caught a regression that fully-passing
  synthetic unit tests did not. The corrector remains in the codebase,
  fully tested, available for opt-in use if you understand and accept
  that tradeoff; see its module docstring for the complete writeup.

## Golden-file regression test

`tests/golden/test_manual_proofread_regression.py` compares the full
pipeline's output against a manually-proofread reference (pages 11-73
of the source book) and fails if quality regresses below the recorded
baseline in `tests/golden/baseline.json`.

The underlying book text (`tests/golden/data/*.txt`, `*.docx`) is
**not** committed — see `tests/golden/data/.gitignore` — per this
project's data policy. The test skips (doesn't fail) when that data
isn't present locally.

```bash
# Normal test run -- golden test auto-excluded (see pyproject.toml addopts)
pytest tests/ -v

# Explicit golden-file run (needs tests/golden/data/*.txt and *.docx present)
pytest tests/golden/ -v -m golden
```

Current baseline (60 of 63 pages in range; 3 excluded for documented
data-quality reasons -- see `tests/golden/baseline.json`):

| Metric | Value |
|---|---|
| Overall word-level similarity | 92.3% |
| Palochka recall (exact-word recovery of Ӏ-words) | 76.9% |

Pages 24 and 33 were originally excluded as "missing from raw OCR" --
their photos existed but had been misattributed to pages 19 and 31
(a page-number misread). Resolved once the project owner supplied the
original scan photos confirming both the visible printed page number
and a near-verbatim text match; see `tests/golden/manual_resolutions.py`.

See `tests/golden/manual_resolutions.py` for the audited table of
page-attribution fixes (misattributed/duplicate scans, page numbers
recovered from the "номер не распознан" bucket) applied before these
metrics were computed.
