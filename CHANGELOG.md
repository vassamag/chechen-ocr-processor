# Changelog

All notable changes to `chechen_ocr` are documented here. Format loosely
follows [Keep a Changelog](https://keepachangelog.com/); versioning
follows [Semantic Versioning](https://semver.org/).

Versions before 6.0.0 lived as standalone scripts in `src/`
(`process.py`, `run_pipeline.py`, `normalize_palochka_final.py`, etc.),
tracked informally via filename suffixes (`_v2`, `_FINAL`, `_v5.4`)
rather than git tags — see `docs/OCR_PROCESSOR_V5_4_FINAL_STATUS.md`
for that era's state. 6.0.0 is the first version with a real package
structure, semantic versioning, and this changelog.

## [0.3.0]

Item 10 from the GUI usability discussion, minimal integration (per
project decision: ship the core mechanism and its GUI wiring first
without new visual elements, confirm it behaves correctly on real
documents, then layer on locked-line highlighting / an editable page-
number field / auto-resume-position afterward, once the underlying
mechanism is proven rather than guessed at).

Raised via project discussion: for large multi-page documents, a
person reviewing/correcting flagged words needs their work to survive
being re-processed later (e.g. after a corrector improvement), even
if only part of a page was actually touched.

### Added
- New module `chechen_ocr/review/session.py`: `ReviewSession` /
  `BlockRecord` / `LineRecord` plus supporting functions. Design,
  agreed in discussion beforehand:
  - A block's identity is its ordinal position in the document (or a
    source photo filename, when available) -- NOT the page number
    printed on it, since that can be missing or misread (this
    project has repeated real examples of both). The page number is
    a separate, editable field on the block, independent of its
    identity.
  - Tracking is per LINE, not per block: each line stores both what
    the corrector most recently produced and what's currently saved.
    An unchanged line is safe to reprocess; a changed one (a person
    edited it) is left alone by any future automated run, regardless
    of corrector version -- verified with a test matching the exact
    scenario raised in discussion, half a page edited and half not,
    each line tracked independently within the same block.
  - Session state is a JSON sidecar next to the source file
    (`<file>.review_session.json`), never mixed into the document
    itself.
- GUI wiring (single-file .txt/.docx mode only for now -- batch mode
  and image/PDF inputs are unaffected):
  - Process: loads an existing session for the file if one exists,
    reprocesses only its untouched lines, and saves it back; builds a
    fresh session on first run.
  - Save Edits: reconciles the session with whatever's currently in
    the Corrected Text box, so a manual edit is recognized as such
    the next time Process runs, even without closing the app.
  - Session mutation happens only on the main thread (via the
    existing JobDone/message-queue pattern this app already uses for
    every other background-thread result) -- the background worker
    returns the session rather than assigning `self.review_session`
    directly, avoiding a cross-thread state-mutation bug that would
    have been easy to introduce here.
- New end-to-end GUI test drives the actual App instance through
  Process -> manual edit -> Save Edits -> Process again, and confirms
  the edit survived while the untouched line was refreshed by the
  corrector -- not just the underlying module's unit tests in
  isolation.

### Not yet done (deferred per project decision, see intro above)
- No visual indication in the GUI of which lines are "locked" by a
  previous edit.
- No editable page-number/verified-status field on a block.
- No auto-resume to `last_position` on reopening a file (the field
  exists in `ReviewSession` and is wired through save/load, just not
  surfaced or acted on by the GUI yet).
- Batch mode (directory of images) doesn't use this yet -- each file
  in a batch already has a natural block identity (its filename), but
  wiring it through `BatchProcessor` wasn't part of this pass.

## [0.2.6]

CI advanced past 0.2.5 (collection succeeded) but failed again, at
the same "Unit tests" step, on 5 tests in `tests/io/test_pdf_reader.py`.

### Fixed
- Root cause: same class of bug as 0.2.4/0.2.5, a third instance --
  `pdf2image` (installed via the `.[pdf]` extra) is only a thin
  Python wrapper around the `poppler` command-line tools
  (`pdftoppm`/`pdftocairo`/`pdfinfo`); it does nothing without the
  system package `poppler-utils` installed separately, which the CI
  workflow's apt-get step never included. Verified by reproducing
  locally with poppler's binaries hidden from `PATH` (not just
  "not run" -- actually absent) before and after the fix; got the
  exact same 5 failures and the exact same
  `PDFInfoNotInstalledError: Unable to get page count. Is poppler
  installed and in PATH?` CI reported.
- Added `poppler-utils` to the CI apt-get install step.
- Proactively added `tesseract-ocr` and `tesseract-ocr-rus` too, even
  though no current test invokes the real Tesseract binary (only its
  error paths, on missing/corrupt files, are exercised) -- the same
  gap (Python wrapper installed, system binary not) exists for
  `pytesseract` and would fail the same way the moment a real-
  recognition test is added. Caught proactively this time instead of
  reactively.
- Third time this exact failure MODE (works locally, fails in CI)
  showed up in three consecutive versions (0.2.4: missing type stubs,
  0.2.5: missing pythonpath config, 0.2.6: missing system packages) --
  all traced to the same underlying cause: a long-lived local dev
  environment accumulating things (stub packages, system binaries)
  that were never actually declared as project requirements anywhere.
  None of this would keep recurring if local verification were run in
  a genuinely fresh environment before pushing, rather than the
  existing dev setup -- noted as a real process gap, not just three
  unrelated bugs.

## [0.2.5]

CI advanced past the 0.2.4 fix (lint/format/mypy all passed) but
still failed, now at the "Unit tests" step, uniformly on all 3 Python
versions again ("exit code 2" this time, not 1 -- a different failure
than 0.2.4's).

### Fixed
- Root cause: `tests/golden/test_manual_proofread_regression.py` does
  `from tests.golden.golden_diff import run_golden_diff` -- an
  absolute import that requires the repo root to be on `sys.path` so
  `tests` resolves as a top-level package. `pyproject.toml`'s
  `[tool.pytest.ini_options]` was missing `pythonpath = ["."]`, which
  is what makes that happen automatically. This exact setting was
  already known to matter for this maintainer's other project
  (Windows pytest path issues) but hadn't been carried over into this
  one -- it must have been lost somewhere during the repository
  recreation. Every local verification in this session had been
  masking it by manually prefixing `PYTHONPATH=.` on every pytest
  invocation, which CI's plain `pytest tests/ -v --tb=short` doesn't
  do.
- Added `pythonpath = ["."]` to `[tool.pytest.ini_options]`. Verified
  by reproducing the CI command with `PYTHONPATH` explicitly unset
  (not just omitted -- actually cleared from the environment) before
  and after the fix.
- Second lesson on top of 0.2.4's: convenience flags used habitually
  in every local test run (like `PYTHONPATH=.`) can mask exactly the
  kind of environment-dependent bug CI exists to catch. Worth
  periodically running the *exact* CI command, unmodified, locally.

## [0.2.4]

CI failed on all 3 Python versions (3.10/3.11/3.12) uniformly after
pushing 0.2.3, with a bare "Process completed with exit code 1" and
no other visible detail in the summary.

### Fixed
- Root cause: `mypy` requires type stubs for `yaml` (used in
  `dictionaries.py`), and the `dev` extra in `pyproject.toml` didn't
  declare `types-PyYAML`. This was silently masked in the maintainer's
  local dev environment (stubs had been installed there earlier in
  the session, unrelated to this project's own dependency list) but
  fails immediately in any genuinely fresh install -- which is exactly
  what CI does on every run. Reproduced by installing into a brand
  new venv from scratch (not just re-running tests in an
  already-set-up environment) -- that's the only way this class of
  bug reliably surfaces locally.
- Added `types-PyYAML>=6.0` to the `dev` extra.
- Lesson for future dependency changes: verify in a clean venv, not
  just the existing dev environment, since a long-lived local
  environment can accumulate packages that mask missing declarations.

## [0.2.3]

### Changed
- `APP_BORDER_THICKNESS`: 3 -> 9, per project discussion.

### Fixed
- The previous edit (0.2.2) accidentally left a duplicated comment
  block and a duplicate `APP_BORDER_THICKNESS = 3` line in the source
  (harmless -- the second assignment just silently won -- but sloppy).
  Cleaned up to a single constant with one comment block.

## [0.2.2]

Raised via project discussion: the border color from 0.2.1
(`APP_BORDER_COLOR = "#8a8f98"`) was a guess, not a match to what the
"background seam" actually looked like before it became intentional.

### Changed
- Border color is no longer a hardcoded hex constant. It's now read
  from the root window's own default background at runtime
  (`self.root.cget("background")`), which is exactly where the seam's
  color came from in the first place -- guaranteed to match, rather
  than approximated, and correctly follows system/theme defaults
  instead of a value picked for one specific system.
  `APP_BORDER_THICKNESS` remains a plain constant (unaffected).

## [0.2.1]

Follow-up polish after first real use of 0.2.0, raised via project
discussion (a screenshot-driven back-and-forth to pin down an
intermittent thin light line between the notebook and the status bar
-- named "фоновый шов" / "background seam" in discussion once its
cause was identified, for faster reference going forward).

### Fixed
- The "background seam": a `pady=(0, 14)` gap under the notebook let
  the root window's own background color show through as a thin line
  above the status bar. Root cause, not just this one seam: the
  notebook and status bar had inconsistent horizontal insets from the
  window edge too (notebook had padx=14, status bar had none),
  described in discussion as the border not going "all the way
  around."
- Turned that into an intentional design element instead of removing
  it: added an outer border frame (constant color/thickness,
  `APP_BORDER_COLOR` / `APP_BORDER_THICKNESS` in `gui/app.py` --
  code-only per project discussion, no Settings UI for it) that wraps
  the entire window, with all content inset from it equally on every
  side.
- Suspicious Words table: word/reason/candidates/replacement columns
  are now center-aligned (previously left-aligned with no padding,
  which read as "stuck to the edge").
- Notebook tabs (Log/Corrected Text/Suspicious Words/...) had no
  spacing between them and visibly shifted size when clicked (ttk's
  default "sunken" selected-tab styling) -- added consistent padding
  via `ttk.Style` for both selected and unselected states so the tab
  no longer visibly moves on click.

## [0.2.0]

Ten GUI usability issues raised via project discussion after using
the desktop app for the first time on a real docx file. Addressed
eight of them; one (window title bar color) is OS-level chrome and
was left as-is on purpose; the tenth (a persistence/resume system for
partially-reviewed large documents) was designed in discussion but
not yet implemented -- see the design notes below, planned for a
following release.

### Fixed
- Toolbar and text-area padding was too tight (content touching the
  window edge) -- increased throughout (8px -> 12-14px).
- Settings dialog opened at an OS-default screen position, sometimes
  landing outside the main app window -- now centers itself over the
  parent window on open.
- The "Source" selector's labels named specific technologies
  ("Scan (Tesseract)" / "Pre-recognized (Vision)") when the engine
  behind either choice can be anything -- relabeled to describe the
  nature of the input instead ("Scanned image" / "Recognized text").
- No visible confirmation when processing finished -- a "Done." line
  only appeared in the Log tab, easy to miss. Added a persistent
  status bar at the bottom of the window, updated on process start,
  completion (with correction/flagged-word counts), and export.
- Suspicious Words table columns had no visual separation and text
  sat flush against the column edge -- added per-column anchoring
  (center for id/page/decision, left-aligned with padding for text
  columns) and increased row height.
- The Page column was empty for every row when processing a DOCX
  using the bold-digit-marker-per-page convention (e.g.
  combined_11_236_one_page_per_sheet.docx) -- `review/schema.py`'s
  `build_page_index()` only recognized the
  "===== Страница N | file.jpg =====" service-header format used by
  `ocr_book_directory.py`-style output. Added a fallback that detects
  standalone-digit-only lines (the bold marker itself doesn't survive
  DOCX-to-plain-text flattening, but the line does).
- No obvious way to choose where to save the finished file -- "Save
  Edits" only commits the Corrected Text textbox into memory, it
  never writes to disk, and the actual file-save (Export TXT/DOCX/
  review CSV, all of which already used a proper save-location
  dialog) was buried in the File menu. Added a visible "Export..."
  button directly in the main toolbar.

### Design note: page-block identity for large-document review (item 10)
For documents too large to fully review in one sitting, agreed
design (not yet implemented):
- A block's identity for tracking purposes is its position in the
  document (or source photo filename, when available) -- NOT the
  page number printed on it, since that can be missing or misread
  (this project's own source material has repeated real examples of
  both). The page number is a separate, editable/flaggable field on
  the block, independent of its identity.
- Per-line tracking, not per-page: for each line, store what the
  corrector produced and what's currently saved. Unchanged lines
  (saved == corrector output) are safe to reprocess on a future run
  (e.g. after a corrector improvement); changed lines (a person edited
  them) are left untouched by any future automated run, regardless of
  version.
- The last edit position is saved and restored on reopening the file,
  so review can resume where it left off rather than starting from
  the top every time.

## [0.1.0]

Version numbering restarts here, at the new repository
`vassamag/chechen-ocr-processor` (superseding an earlier, informal
script collection previously at the same name/location — see below).
This is not a fresh rewrite: the codebase is exactly what was
`6.9.9` under the old ad-hoc numbering, carried forward unchanged.
`0.x.y` from here means active development, where the public API may
still change; `1.0.0` will mark the first release considered stable.
Everything below this entry (6.0.0 through 6.9.9) is kept as-is for
historical reference -- it documents real decisions, including
several tried-and-reverted experiments (WordSegmentationFix, an
earlier unconditional InternalCapitalizationFix) that are worth
knowing about even though the version numbers themselves no longer
mean anything relative to 0.1.0 onward.

## [6.9.9]

Raised via project discussion, from GUI use on a second, different
book's Vision output ("pages_new_full", 209 pages): the GUI's
Suspicious Words tab showed a large number of "mixed Latin/Cyrillic
characters" flags that weren't getting auto-fixed.

### Fixed
- Diagnosed a real architecture gap: `is_suspicious_word`'s "mixed"
  check flags ANY token containing both a Latin and a Cyrillic letter
  (`[A-Za-z]` + `[А-Яа-яЁёӀ]`), while `LatinCyrillicHomoglyphFix` only
  fixes the specific letters in its verified mapping table -- a much
  narrower set. Any Latin letter outside that table gets flagged but
  never auto-corrected, by design (no verified-safe substitution
  exists for it yet).
- Diagnosed which unmapped letters were actually responsible on this
  book: t (43), r (29), h (24), k (21), u (19), n (18), s (18), m (15),
  d (14), g (12), plus several rarer ones and their uppercase forms --
  a much wider spread than "Эха буьйсанаш" had shown.

### Added
- `LatinCyrillicHomoglyphFix`: added t->т, k->к, n->н, u->у to the
  mapping table. Verified each candidate against the dictionary the
  same way as every previous addition (0% of word-adjacent tokens
  already valid as literal Latin letters; confirmation rate after
  substitution: t 19.6% of 51, k 22.7% of 22, n 16.0% of 25, u 15.8%
  of 19 -- comparable to the 15-39% range that supported 1/l).
- Explicitly did NOT add h->х (4.2% of 24), m->м (5.9% of 17),
  d->д (6.7% of 15), or r->г (3.0% of 33, and r/г aren't even clear
  visual look-alikes) -- too little confirmation to be confident,
  unlike the four that were added.
- Measured on the same book: suspicious-word rate dropped further
  (mixed-Latin/Cyrillic flags 216 -> 143, total suspicious 507 -> 434).

## [6.9.8]

Raised via project discussion: the GUI had no way to choose Vision vs
Tesseract correction rules when loading an already-recognized .txt
file, so it silently always applied the Tesseract-pattern correctors
and never InternalCapitalizationFix -- confirmed via a real run,
where the missing corrector was visibly absent from the applied-rules
list and the suspicious-word rate was correspondingly higher than
expected for Vision-sourced text.

### Added
- GUI: a "Source" selector (Scan/Tesseract vs Pre-recognized/Vision)
  in the main toolbar, wired through to both the single-file (.txt)
  and batch processing paths. Selecting "Pre-recognized (Vision)"
  does not trigger any OCR -- it only changes which correction rules
  apply, exactly like passing `ocr_engine_name="openai_vision"` to
  `process_text()` directly.
- `BatchProcessor.process_directory()` now accepts an
  `ocr_engine_name` parameter (previously always used the default/
  Tesseract-pattern rule set unconditionally), passed through to the
  underlying `process_text()` call.
- New test verifying the parameter actually changes correction
  behavior (`InternalCapitalizationFix` fires for "openai_vision" and
  not for "tesseract", the reverse of the Tesseract-specific
  correctors).

## [6.9.7]

Found while running the processor on a different book's already-
manually-corrected reference text (11-73) as a sanity check -- a
correction fired on text that should have needed none.

### Fixed
- Removed `ааи` from `rules/chechen_words.txt` -- confirmed leftover
  contamination from the 6.8.2 extraction (the same class of garbage
  fragment documented and partially cleaned in 6.8.5, this one
  apparently missed or reintroduced by a later merge). Its presence
  caused `SingleCandidateDictionaryFix` to "confidently" rewrite the
  proper noun "Ази" to "Ааи" via the з->а confusion pair, since "ааи"
  passed dictionary verification. Removing the contaminating entry
  eliminates the false positive; golden-file baseline moved slightly
  in the right direction as a side effect (92.41% -> 92.43%).

## [6.9.6]

Follow-up to 6.9.5's revert, raised via project discussion: "can we
tell which of the remaining uppercase-inside-word errors are actually
palochka-related vs pure case errors, by checking against the known
тг/кт-style confusion patterns we already have?"

### Fixed
- Classified all 1,851 "uppercase letter inside word" flags on the
  full "Эха буьйсанаш" book against the existing PAIR_REPLACEMENTS
  patterns (the same тг/кт/etc. table SingleCandidateDictionaryFix
  already uses): only 4 (0.2%) matched a known palochka-confusion
  position. This explained the 6.9.5 regression's actual scope --
  it was specific to Tesseract output, where PatternBasedPalochka's
  lowercase-only pattern matching creates real collisions with
  case-fixing; Vision-generated text essentially doesn't have this
  problem.
- Re-enabled `InternalCapitalizationFix` in the default pipeline,
  gated the OPPOSITE way from the Tesseract-specific correctors: only
  for engines other than Tesseract (verified this restores the golden
  baseline exactly, 92.41% / 77.33%, since the corrector never runs
  for engine=None/tesseract).
- Net effect on the book: suspicious-word rate 2.05% -> 1.41%
  (1,174 corrections applied). "mixed Latin/Cyrillic characters"
  (1,038) is now the largest remaining category.

## [6.9.5]

Raised via project discussion: the Ш/П/И-specific hypothesis didn't
pan out (see 6.9.4 follow-up), but a simpler, letter-independent one
was proposed instead -- "a capital letter mid-word or word-final is
just a case error, regardless of which letter it is; fix the case,
not the letter identity."

### Tried and reverted
- Implemented `InternalCapitalizationFix`, generalizing the case-only
  fix to every letter (not just Ш/П/И), reusing the exact exemption
  logic already used by the existing suggestion-only candidate
  generator (`_normalize_internal_uppercase_candidate`): skip fully-
  uppercase words, skip the palochka, skip a capital right after a
  hyphen.
- Golden-file testing found a real regression: 92.41% -> 92.26%
  overall similarity, 77.33% -> 76.45% palochka recall. Root cause: on
  Tesseract output, an unexpected capital mid-word is often the FIRST
  symptom of a still-unresolved palochka lookalike (e.g. "тГаьххьара"
  should become "тӀаьххьара" via the already-known тг->тӀ pattern, but
  `PatternBasedPalochka`'s pattern only matches lowercase "г"). Fixing
  the case first silently produces a confidently wrong word AND
  removes it from the suspicious-word queue (no longer mixed-case) --
  worse than before, since the error becomes invisible instead of
  flagged.
- Removed from the default pipeline (`processor.build_pipeline()`).
  The module and its 8 passing unit tests remain in the codebase for
  explicit opt-in via a custom `Pipeline`, same treatment as
  `WordSegmentationFix` since 6.4.0 -- the underlying idea may still be
  usable once the pattern-based palochka correctors are taught to
  recognize uppercase lookalikes too, but that's a separate piece of
  work, not this one.

## [6.9.4]

Raised via project discussion: after fixing I/i/1, what does the
remaining "mixed Latin/Cyrillic" category look like structurally?

### Changed
- `LatinCyrillicHomoglyphFix` now also maps lowercase Latin "l" to the
  palochka (Ӏ), unconditionally, same as I/i/1. Diagnosed by breaking
  down which Latin letters remained in still-flagged "mixed" words
  after 6.9.2/6.9.3: "l" was the single largest remaining cause
  (2,213 of ~3,133 occurrences), overwhelmingly appearing right after
  a consonant in the same гӀ/кӀ/хӀ/тӀ position pattern already well
  established in this project. Verified the same way as before: 0% of
  word-adjacent "l" tokens were already valid dictionary words, 21-39%
  became verified after the substitution. Uppercase "L" was NOT
  included -- comparatively rare in the data and less clearly always-
  wrong.
- Measured on the full book: suspicious-word rate 3.31% -> 2.05%
  (~5.6 words/page, down from ~27.5/page before this whole 6.9.x
  series of fixes). "uppercase letter inside word" (1,851) is now the
  largest remaining category -- a structurally different, harder
  problem (scattered/chaotic capitalization, not a single clean
  substitution) that doesn't have an obvious safe automatic fix the
  way the homoglyph confusions did.
- No change to the golden-file baseline -- "l" wasn't a meaningful
  factor in the Tesseract-sourced corpus.

## [6.9.3]

Raised via project discussion: "if a digit 1 is inside, at the start,
or at the end of a word, isn't that unambiguously an error?"

### Changed
- `LatinCyrillicHomoglyphFix` now also maps an ISOLATED digit "1"
  (not part of a longer digit run) to the palochka (Ӏ) when glued to
  Cyrillic letters, using the same unconditional-but-guarded approach
  as the 6.9.2 I/i fix. A standalone multi-digit number (a year, a
  page count, "2014", "10") is protected by a dedicated "not part of a
  longer digit run" check, verified with dedicated tests -- even a
  pathological case like "2014года" only touches an isolated "1", not
  the year itself (there wasn't one in this example, but the guard is
  tested directly).
- Verified against real book data first, per the same discipline as
  6.9.2: of ~3,600 word-adjacent "1" occurrences in "Эха буьйсанаш",
  zero were already valid dictionary words as literal digits, while
  23-36% became verified dictionary words after the substitution.
- Measured on the full book: suspicious-word rate 4.99% -> 3.31%.
  The "contains suspicious OCR char '1'" category collapsed from
  2,915 to 83 (the remainder being cases where "1" was correctly
  identified as part of a genuine multi-digit number and left alone).
- Golden-file baseline updated: 92.41% / 77.33% (was 77.28%) -- this
  corrector now runs for every engine (not just Vision), and Tesseract
  output turns out to exhibit a small amount of the same digit-for-
  palochka confusion, previously uncaught.

## [6.9.2]

Raised via project discussion: "Latin I mixed with Cyrillic I is a
code-level confusion I can't see visually -- am I wrong to think this
is basically unambiguous in Chechen text?" Agreed: genuine Latin I
essentially never occurs inside a Cyrillic Chechen word.

### Changed
- `LatinCyrillicHomoglyphFix` now includes Latin "I"/"i" in its
  unconditional mapping (both -> palochka Ӏ), promoted out of
  `SingleCandidateDictionaryFix`'s dictionary-gated handling of the
  same character. This was the actual cause of most "mixed Latin/
  Cyrillic" suspicious flags: the correct candidate was already being
  generated, just discarded for not being a verified dictionary entry
  for many of this book's specific word forms. The existing "must
  coexist with an unambiguous Cyrillic letter in the same token" guard
  is what keeps genuine Roman numerals (e.g. "III", "IV" in chapter
  headings) untouched -- verified with dedicated tests.
  Deliberately still excludes "1"/"l" -- a standalone digit or lowercase
  L is more plausibly genuine (e.g. a real page number) than a Latin
  "I" ever is inside Cyrillic prose, so those remain gated behind
  dictionary verification as before.
- Measured on the full "Эха буьйсанаш" book (591 pages, 161,883
  words): suspicious-word rate 10.03% -> 4.99% -- for the first time
  under this project's own 5% review-priority threshold. Corrections
  applied by this one corrector: 3,052 -> 14,067.
- No change to the existing golden-file baseline (92.41% / 77.28%) --
  expected, that corpus is Tesseract-sourced and doesn't exhibit this
  artifact.

## [6.9.1]

### Added
- Expanded `rules/chechen_words.txt` (+2,330 words) and
  `rules/palochka_words.txt` (+338 words), extracted from the
  CORRECTED (post-pipeline, not raw) Vision transcription of "Эха
  буьйсанаш" -- a meaningfully cleaner source than the 6.8.2/6.8.6
  extractions, which came from the book's noisy embedded-OCR text
  layer.

### Investigated and scoped down
- Naive extraction (any word not currently flagged suspicious) found
  60,158 "new" words -- but a length/shape spot-check showed short
  candidates (<=4 chars) were dominated by clear noise (e.g. "могх",
  "прно", "мньа") that simply didn't happen to trigger any of this
  project's specific suspicious-word heuristics (which look for known
  OCR-confusion signatures, not general word-plausibility). A
  frequency filter (word must appear >=2 times) cut the candidate
  pool to 5,163 but did not fully solve this -- some short "words"
  repeated identically across pages while still being clear artifacts
  (e.g. "уьуь", "орд", "тод"), suggesting a systematic Vision-
  generation quirk rather than random noise. Spot-checking length>=6
  candidates, by contrast, showed consistently plausible real words.
  Restricted the addition to that safer subset (2,330 of the original
  60,158) rather than risk contaminating the dictionary the way 6.8.2
  did (later cleaned up in 6.8.5).
- Net effect on this book's own suspicious-word rate: 10.17% -> 10.03%,
  a modest, honest improvement -- most of the remaining rate is short
  words or genuine review-worthy cases that this conservative
  extraction correctly declined to touch automatically.

## [6.9.0]

Raised via project discussion: running the full "Эха буьйсанаш" book
through the OpenAI Vision API directly produced a suspicious-word rate
of ~11.5%, dramatically higher than the ~1-2% seen from the same
model used through the ChatGPT chat product for smaller batches.

### Added
- New corrector `LatinCyrillicHomoglyphFix`
  (`correctors/latin_cyrillic_homoglyphs.py`), added to the default
  pipeline for all engines: fixes individual Latin letters that are
  visually IDENTICAL to a Cyrillic letter (a/e/o/p/c/x/y and their
  uppercase forms, plus B/H/K/M/T) generated in the middle of an
  otherwise-Cyrillic word -- a known LLM-text-generation artifact, not
  a scanned-image OCR error. Only touches a token that contains both
  an unambiguous Cyrillic letter and a mappable Latin one, so genuine
  Latin-only tokens (acronyms, Roman numerals) are never touched.
  Deliberately does not include I/1/l -- those remain the palochka
  correctors' job.
  Diagnosed via a 50-page sample: 68% of all suspicious-word flags
  were this exact homoglyph-mixing artifact, not genuine transcription
  problems. Measured on the full 590-page book: 3,052 words fixed,
  overall suspicious rate 11.48% -> 10.17%.
- No change to the existing golden-file baseline (92.41% / 77.28%,
  unchanged) -- expected, since that corpus is Tesseract-sourced and
  doesn't exhibit this Vision-API-specific artifact at all, so the new
  corrector correctly never fires on it.

### Investigated and left as-is
- Most of the remaining ~10% suspicious rate traces to capital Latin
  "I" used in place of the palochka (Ӏ) -- but this is NOT the same
  bug: `generate_palochka_candidates` already produces the correct
  candidate (e.g. "ЦIацхоьу" -> "ЦӀацхоьу"), it's just not verified in
  `palochka_words.txt` for many of this book's specific inflected
  forms, so `SingleCandidateDictionaryFix` correctly declines to
  auto-apply it (same structural dictionary-coverage gap documented
  since 6.4.0/6.7.2). Confirmed via direct testing, not assumed. The
  path forward for this is more dictionary growth (as in 6.8.x), not a
  pipeline change.

## [6.8.6]

### Added
- Expanded `rules/chechen_words.txt` (+2,394 words) and
  `rules/palochka_words.txt` (+378 words) from a PDF version of the
  same book already used in 6.8.2 ("Эха буьйсанаш"), supplied after
  the original .txt was flagged as a possibly lower-quality copy.
- Honest finding: character-level diagnostics (word-internal digit
  "1" count, Latin "I"/"l" counts) were nearly identical between the
  .txt and this PDF's extracted text layer, and the PDF showed the
  same contamination patterns already found and fixed in 6.8.5 (new
  `ы`-initial fragments, 20+ character merged-word artifacts) at a
  similar rate. This appears to be the same underlying digitization,
  not a meaningfully cleaner source -- but line-break handling
  differed enough between the two extractions to surface some
  genuinely new, clean vocabulary after the same filtering (length/
  shape sanity check + no `ы`-initial entries, per 6.8.5) was applied
  again before merging.

## [6.8.5]

Raised via project discussion: "I'm almost certain there's no case in
Chechen where и follows а directly, and 100% certain no Chechen word
starts with ы."

### Fixed
- Verified both claims against the dictionary and found real
  contamination from the project's own 6.8.2 book extraction
  ("Эха буьйсанаш"): 53 of 54 words starting with `ы` and 265 of 493
  lowercase words containing `аи` traced directly back to that
  extraction -- merged-word/line-wrap fragments the 6.8.2 length/shape
  filter didn't catch (it checked length and hyphen count, not
  phonotactic plausibility). Removed all 54 `ы`-initial entries and
  those 265 `аи`-containing fragments from both `chechen_words.txt`
  and `palochka_words.txt` (107,341 -> 107,022 / 26,542 -> 26,506).
- The `ы`-initial claim held essentially without exception (53/54).
  The `аи` claim, however, does NOT hold at the morpheme boundary --
  228 remaining `аи`-containing words traced to other sources (mostly
  the NM-development corpus's heavy Bible content) turned out to be
  genuine: inflected forms of "Исраил" (Israelites, in various cases)
  and verb forms with a causative infix at a root/suffix boundary.
  Those were deliberately kept. This nuance -- true within a root,
  not true across a morpheme boundary -- is exactly the kind of thing
  a blanket rule would have gotten wrong; the per-word provenance
  check (does this exact string appear in the source text this
  dictionary addition came from) is what made the distinction
  possible.

## [6.8.4]

Raised via project discussion, same family as 6.8.3: "the same thing
happens with ы -- ь gets replaced by ы a lot too."

### Added
- New `GeneralWordFix` confusion pair: `аы` -> `аь` (OCR turning the
  "аь" digraph into "аы" after а, the same mechanism as the 6.8.3
  `ав` -> `аь` pair, just a different lookalike substitution for the
  same letter). Verified against the project's own raw OCR text
  first: only 4 clean, unambiguous matches found in the golden-file
  corpus (vs. 29 for `ав` -> `аь`) -- a real pattern, just markedly
  rarer in this corpus. Added anyway since the safety mechanism (must
  be the single dictionary-valid candidate) makes a rare-but-real
  pair effectively free to include; no measurable change to the
  golden-file baseline's headline numbers at this volume (92.42% /
  77.28%, unchanged to 2 decimal places).

## [6.8.3]

Raised via project discussion: "during manual editing I noticed many
replacements of ав to аь -- аь is an alphabet letter, might there be a
systematic pattern here?"

### Added
- New `GeneralWordFix` confusion pair: `ав` -> `аь` (OCR turning the
  soft-sign digraph "аь" into "ав" specifically after а). Verified
  directly against the project's own raw OCR text before adding: 29
  clean, unambiguous matches (a token containing "ав" that isn't a
  valid dictionary word on its own, but becomes one after the
  substitution) found in the golden-file corpus alone -- including
  "Аврзу" -> "аьрзу", the same name already known from the 6.4.0 "з/а"
  and "ъ/ь" findings ("Аързу" -> "Аьрзу"), confirming OCR mangles the
  same "ь" in this word inconsistently across different scans.
- Golden-file baseline updated: overall similarity 92.34% -> 92.42%,
  palochka recall 76.86% -> 77.28% (1316/1703, was 1309/1703).

## [6.8.2] (dictionary expansion)

### Added
- Expanded `rules/chechen_words.txt` (+21,914 words) and
  `rules/palochka_words.txt` (+4,204 words) from a second user-provided
  book ("Эха буьйсанаш" by Abuzar Aydamirov). Same vocabulary-only
  extraction as 6.8.1 -- unique lowercased word forms only, no prose
  retained.
- This source used the digit "1" (not Latin "I") as its palochka
  stand-in, and used it inconsistently -- 18,068 word-internal
  occurrences (almost certainly palochka) vs. 1,318 standalone ones
  (almost certainly genuine numbers/page markers), a very different
  ratio from Latin "I" in the same file (359 word-internal vs. 4,538
  standalone, i.e. mostly NOT palochka, likely Roman-numeral chapter
  headings). Normalized only the word-internal "1" occurrences,
  leaving standalone digits and Latin "I"/"l" untouched.

### Fixed
- Found and filtered 95 merged-word artifacts (run-together words
  with no space, apparently from the source file's own formatting,
  not from any OCR step) before they could enter the dictionary --
  e.g. multi-word strings 20+ characters long that would have looked
  like a single implausible "word." Applied a length/shape sanity
  filter (2-18 chars, must contain a real Cyrillic letter, at most 2
  hyphens) before merging into the dictionary files, consistent with
  the 6.4.0 finding that a dictionary containing garbage entries can
  actively hurt future word-segmentation-style corrections.

### Tried and reverted (fuzzy-match candidate fallback)
- Prototyped a fuzzy (edit-distance) dictionary lookup as a last-
  resort candidate source for suspicious words that no known OCR-
  confusion pattern could generate a candidate for -- raised via
  project discussion questioning whether never "guessing" for
  pattern-less suspicious words hurt review efficiency. Implemented
  as `fuzzy_match.py` (first-character-bucketed index +
  edit-distance ≤ 2, so it stayed fast enough for batch use) and wired
  into `get_suspicious_candidates` as a tier reached only when every
  existing tier came up empty -- deliberately scoped to never add a
  new item to a review queue, only to fill in an otherwise-empty
  candidates cell for a word already flagged.
  Measured on the full golden-file corpus: the fallback fired **zero
  times** across all 125 suspicious words -- every one already had at
  least one candidate from the existing tiers (dictionary-verified,
  pattern-generated-unverified, or the case-only fallback), a direct
  consequence of the 6.7.2 fix plus this same version's dictionary
  growth already having closed that gap on this corpus. Since a
  feature with no measurable effect is just added surface area and
  maintenance cost, reverted per the plan agreed before implementing:
  try it, measure it on our own material, keep it only if it does
  something.

## [6.8.1] (dictionary expansion)

### Added
- Expanded `rules/chechen_words.txt` (+1,416 words) and
  `rules/palochka_words.txt` (+520 words) by extracting unique word
  forms from a user-provided Chechen-language book text ("Жима эла").
  Extraction is vocabulary-only: unique lowercased word forms, no
  sentence order, no repeated occurrences, no prose retained --
  nothing about the source text's content is reconstructable from the
  dictionary files.
  Notable finding during extraction: the source file used plain Latin
  "I" throughout instead of the canonical palochka codepoint (Ӏ,
  U+04C0) -- 2,246 occurrences, zero uses of the correct character.
  Normalized (I -> Ӏ) before extracting vocabulary, since Chechen text
  has no genuine Latin-script words this substitution could
  incorrectly affect. This is the same class of issue the whole
  project exists to fix, just encountered in a differently-sourced
  text (a plain-text book file, not OCR output) -- some source texts
  simply never used the correct Unicode character in the first place,
  independent of OCR.

## [6.8.0]

### Added
- Expanded `rules/chechen_words.txt` (+3,446 words) and `rules/palochka_words.txt`
  (+3,384 words) using single-word dictionary entries from the
  `NM-development/nmd-ce-ru-171k-v0` parallel corpus (Matsiev's
  Chechen-Russian dictionary, Bersanov's anatomy dictionary, and the
  computer-vocabulary dictionary sources specifically -- not the
  corpus's Bible/news/literature sentence pairs, which are a
  different register and out of scope for a word-existence check).
  81.8% of the corpus's ~19.4k single-word terms were already present
  in our dictionaries; of the ~3.4k genuinely new ones, 96.8%
  contain the palochka (Ӏ) -- directly strengthening
  `SingleCandidateDictionaryFix` and `GeneralWordFix`'s dictionary-
  verification step, which is exactly where the 6.7.2 finding (a
  correctly-generated candidate discarded for not being in the
  dictionary) showed real impact.
  No measurable change on this project's own golden-file corpus
  (92.3%/76.9%, unchanged) -- expected, since the new words are from
  a general dictionary rather than this specific novel's vocabulary;
  the benefit is broader dictionary completeness for future books/
  texts, not a fix for anything already measured here.

## [6.7.5]

Raised via real-world usage: the header row still didn't visually
separate from the data below it, and columns had no vertical
separation either.

### Fixed
- Switched to the `clam` ttk theme explicitly. Windows' native theme
  (`vista`/`winnative`) mostly ignores custom relief/border/background
  settings on `Treeview.Heading` -- it draws headers using native OS
  routines regardless of what ttk style options say, which is why the
  6.7.4 header styling attempt had no visible effect on Windows even
  though it looked fine under Linux/Xvfb during testing. `clam` is
  fully ttk-drawn (not delegated to the OS) and actually honors these
  settings. The header now has a distinct gray background and a
  visibly raised, bordered look, clearly separating it from the rows.

### Known limitation (not fixed, documented instead of faked)
- Persistent vertical gridlines *between columns in the data rows*
  are not implemented. `ttk.Treeview` does not support per-cell
  borders natively on any theme -- getting real spreadsheet-style
  column gridlines would mean replacing the widget entirely (e.g. a
  custom grid of Label widgets, or a third-party table widget like
  `tksheet`), a substantially bigger change than a style tweak. Column
  boundaries are still visible at the header (each heading segment is
  individually bordered/resizable), just not carried down through the
  body rows.

## [6.7.4]

Raised via real-world usage: rows and columns in the Suspicious Words
(and Per-File) tables had no visual separation at all -- everything
blended into one flat canvas, straining the eyes.

### Added
- Alternating row background colors (zebra striping) in both the
  Suspicious Words and Per-File (Batch) tables.
- Taller rows, a bordered/raised header, and a solid border around
  the table widget itself for clearer visual structure.

## [6.7.3]

Raised via real-world usage: even with clickable candidate buttons,
confirming the (usually correct) top suggestion still took an extra
click before it landed in the Replacement field.

### Added
- Selecting an unedited Suspicious Words row now pre-fills the
  Replacement field with the top (best-ranked) candidate automatically
  -- no click, no typing needed for the common case where the first
  suggestion is simply correct. A different candidate is still one
  click away via the existing candidate buttons. Decision is
  deliberately NOT auto-set to "replace" -- pre-filling a suggestion
  is not the same as approving it; Save Row (or picking a different
  candidate) is still required. Re-selecting a row that was already
  edited shows the saved replacement, not the pre-fill.

## [6.7.2]

Raised via project discussion: "originally suspicious words were
meant to suggest several replacement variants, but the current
implementation only ever suggests one."

### Fixed
- `get_suspicious_candidates` filtered out pattern-generated
  candidates that weren't verified present in `palochka_words.txt`,
  falling back only to a (usually wrong) case-normalization
  candidate. This is the correct conservative gate for auto-
  correction (`SingleCandidateDictionaryFix`), but actively hurt the
  human-facing suggestion list: a correctly pattern-generated
  candidate (e.g. "бТаьхоша" -> "бӀаьхоша") is often simply missing
  from an ~80k-word dictionary as a specific inflected form (Chechen's
  agglutinative morphology again -- see the 6.4.0 WordSegmentationFix
  finding), even though it's obviously correct once a person sees it.
  Now surfaces dictionary-verified candidates first, then unverified
  pattern-generated ones, then the case-only fallback -- a human
  judges correctness visually anyway, so hiding a plausible answer
  helped no one.
- Measured impact on the golden-file corpus (131 suspicious words,
  pages 11-73): words with at least one suggested candidate went from
  80.9% to 100%; words with a *palochka-containing* (i.e. plausibly
  actually-correct) candidate went from 3.8% to 48.1%.

## [6.7.1]

Raised via real-world usage: after applying changes, finding the
words that changed (or the ones still flagged) meant searching the
whole text by eye. See project discussion.

### Added
- Corrected Text tab now highlights words the same way the context
  panel does: still-flagged suspicious words in yellow, words just
  fixed via "Apply All Reviewed Changes" in green -- both use the same
  word-boundary matching as the actual replacement step
  (`review.apply_review_table.WORD_CHARS`), so highlighting reflects
  exactly what would (or did) get replaced, not an arbitrary substring
  match. A small color legend was added to the tab's toolbar.
- Highlighting refreshes after processing, after applying reviewed
  changes, and after manual edits (Save Edits) -- always reflecting
  current state rather than a stale first pass.

## [6.7.0]

Raised via real-world usage: choosing the right candidate in
Suspicious Words was hard even for a native speaker without seeing
the word's actual usage. See project discussion.

### Added
- Suspicious Words tab now shows a context panel: selecting a row
  displays the sentence/line the flagged word came from (from
  `ReviewRow.corrected_context`, already computed but not previously
  surfaced in the GUI), with the flagged word itself highlighted.
- Clickable candidate buttons next to the context panel -- click a
  suggested candidate to fill the Replacement field instead of typing
  it by hand (also sidesteps the "how do I type Ӏ" keyboard problem
  for at least the suggested candidates).
- Context panel and candidate buttons clear when a new document is
  processed, so stale content from a previous file can't linger.

## [6.6.3]

Found via real-world GUI usage — marking 4 nearby suspicious words as
"replace" and clicking "Apply All Reviewed Changes" only applied 2 of
them. See project discussion.

### Fixed
- `apply_review_rows` applied rows one at a time against a
  progressively-mutated text. Suspicious words on the same page are
  often close together, so their saved context windows (~160 chars
  each way) routinely overlap -- one row's context can contain
  another row's target word. Applying an earlier row changed the
  text out from under a later row's saved context, causing it to
  report `context_not_found` even with `decision=replace` set
  correctly. Rewrote as a two-pass design: locate every row's target
  span against the original, unmodified text first, then apply all
  accepted replacements in a single pass ordered right-to-left so
  earlier character offsets stay valid. Two rows whose located spans
  would genuinely overlap each other are not both applied -- the
  first (original row order) wins and the second is marked skipped
  (`overlaps_another_row`) rather than risk corrupting the text.

## [6.6.2]

Found via real-world GUI usage — clicking "Apply All Reviewed Changes"
silently did nothing for words in this book's actual text. See project
discussion.

### Fixed
- `apply_review_rows`: context-based matching only tried an exact
  substring match against the real text, and detected-but-skipped
  (rather than actually applying) the common case where
  `build_review_table.py`'s whitespace-normalized context snippet
  doesn't literally appear in the real text. This book's source
  format hard line-wraps each printed line (a real `\n` per line,
  not a flowing paragraph), so essentially any review row whose
  context happened to span a line break was silently skipped even
  with `decision=replace` set correctly. Now falls back to a
  whitespace-tolerant regex match (whitespace in the context matches
  any whitespace in the real text) that finds the real span --
  including its actual newlines, which are preserved -- and applies
  the replacement there. The old "detect and skip" status
  (`context_found_only_after_space_normalization`) is gone; that case
  is now `applied` / `applied_whitespace_tolerant` when a match is
  found.

## [6.6.1]

Found via the first real-world run on an actual Windows machine with a
real scanned book page (not just synthetic test fixtures or Xvfb
screenshots) — see project discussion.

### Added
- Corrected Text tab is now directly editable, with a "Save Edits"
  button — some OCR errors (dropped letters, run-together words
  spanning a phrase boundary) don't fit the "replace one flagged word"
  model the Suspicious Words tab covers; a person needs to fix the
  sentence by hand. Manual edits are taken as final and are not
  re-analyzed for new suspicious words or re-scored in Metrics.

### Fixed
- Notebook tabs and text widgets had no internal padding — text sat
  flush against the widget edge and tabs visually ran together.
  Added consistent padding via a `ttk.Style` configuration and `padx`/
  `pady` on every text widget.

## [6.6.0]

### Added
- `chechen_ocr/gui/` — desktop GUI (Tkinter, stdlib): open a single
  file (image/PDF/TXT/DOCX) or a whole directory (batch mode), process
  in a background thread (UI never freezes), review flagged words
  directly in an editable table (no CSV round-trip required), export
  corrected TXT / highlighted DOCX / review CSV. Tesseract-only in this
  version — no Vision-API key management UI, no TTS/translation
  integration (considered and explicitly deferred).
- CLI: `chechen-ocr-gui`.
- `tests/gui/test_gui_integration.py`: drives the real Tkinter app
  end-to-end (not mocked), needs an actual display — skips gracefully
  without one (mirrors the golden-file test's skip pattern). Added to
  CI under Xvfb (needs no private data, unlike golden-file tests, so
  it runs automatically rather than being deferred to manual runs).

### Fixed
- A real threading bug caught by the GUI's own smoke test before it
  ever reached the test suite: `tk.StringVar`/`IntVar.get()` must only
  be called from the main thread; the background work closure was
  calling `self._build_processor()`, which read several such
  variables, causing hangs. Fixed by reading all Tk variables on the
  main thread before spawning the background thread and passing plain
  values through.

## [6.5.0]

### Added
- `chechen_ocr/security.py`: DOCX zip-bomb protection (inspects ZIP
  central directory for compression-ratio/size/entry-count anomalies
  before `python-docx` decompresses anything) and PDF size/page-count
  limits (via `pdf2image.pdfinfo_from_path`, metadata only) plus a
  render timeout, all before the expensive parsing step.
- New `Settings` fields: `max_docx_file_size_bytes`,
  `max_docx_uncompressed_size_bytes`, `max_docx_compression_ratio`,
  `max_docx_zip_entry_count`, `max_pdf_file_size_bytes`,
  `max_pdf_pages`, `pdf_render_timeout_seconds`.
- `UnsafeFileError` exception, raised by the checks above; already
  compatible with `BatchProcessor`'s existing "skip unreadable file"
  handling.

## [6.4.0]

### Added
- `correctors/general_word_fix.py` (`GeneralWordFix`, in the default
  pipeline): fixes non-palochka Cyrillic letter confusions (ъ/ь, а/з,
  ҳ/х) using `chechen_words.txt`, same "exactly one valid candidate"
  conservatism as the palochka correctors. Verified on the golden-file
  corpus: +0.08 percentage points overall similarity, no palochka
  recall regression.
- `correctors/phrase_disambiguation.py` (`PhraseBigramDisambiguator`,
  in the default pipeline): breaks ties between multiple dictionary-
  valid palochka candidates using a word-bigram index built from
  `chechen_phrases.txt`. Zero corrections fired on the golden-file
  corpus (that corpus turns out to be from an unrelated book), but
  verified harmless; kept for potential benefit on other source texts.
- `correctors/word_segmentation.py` (`WordSegmentationFix`, **not** in
  the default pipeline): splits merged/no-space OCR tokens using
  `chechen_words.txt` word-break decomposition. Fully implemented and
  unit-tested, but excluded from `build_pipeline()` after golden-file
  testing found it net harmful on real data — Chechen's agglutinative
  morphology means real, dictionary-missing words can coincidentally
  decompose into two unrelated valid words. Dropped overall similarity
  from ~92.3% to ~83.8% (unhardened) / ~91.0% (after raising length
  thresholds) — see the corrector's module docstring for the full
  writeup. Available for explicit opt-in.
- `Dictionaries.phrase_bigrams`: word-bigram index derived from
  `chechen_phrases.txt`, built once per `rules_dir` (cached).

### Changed
- `tests/golden/baseline.json` updated: 92.34% overall similarity
  (was 92.26%), palochka recall unchanged at 76.86%.

## [6.3.0]

### Added
- `chechen_ocr/batch.py` (`BatchProcessor`): processes an entire
  directory of scanned pages (any mix of image/PDF/TXT/DOCX) as one
  connected document — concatenates every file's raw text under the
  same page-marker convention and runs `process_text()` once, so
  correction/suspicious-detection/metrics behave identically to
  processing one giant file.
- `BatchResult.worst_files`: per-file quality breakdown sorted by
  suspicious-word ratio, for prioritizing human review.
- CLI: `chechen-ocr-batch <dir> --output-dir <dir>`.
- `ChechenOcrProcessor.process_pdf()` / `io/pdf_reader.py`: rasterizes
  every PDF page and runs it through the configured `OcrEngine` — no
  text-layer detection/extraction, since a PDF with an already-correct
  text layer essentially never occurs in this project's actual input
  (phone-scanned book pages, sometimes bundled into a PDF by a
  scanning app). Requires the optional `pdf2image` extra + system
  `poppler-utils`.

### Fixed
- `OpenAIVisionEngine`: unknown image extensions used to silently
  default to `image/png` regardless of actual format (wrong
  `Content-Type` for e.g. `.tiff`/`.bmp`). Now raises `ValueError`
  before any API call for unrecognized extensions, and recognizes
  `.gif/.bmp/.tif/.tiff` in addition to the original four formats.
- Import bug in `io/pdf_reader.py` caught immediately by its own test
  suite (`from .base import OcrEngine` instead of `from ..ocr.base
  import OcrEngine`).

## [6.2.0]

### Added
- `chechen_ocr/metrics.py` (`DocumentMetrics`, `compute_metrics`):
  per-document correction breakdown by rule, suspicious-word ratio,
  unconverted-lookalike count.
- Standard `logging` throughout `ChechenOcrProcessor` (logger name
  `chechen_ocr.processor`), replacing ad-hoc `print()` calls that
  existed only in CLI entrypoints. INFO-level per-document summary;
  WARNING when suspicious-word ratio exceeds
  `Settings.suspicious_ratio_warning_threshold` (default 5%).
- `ChechenOcrProcessor.compute_metrics(doc)`.

## [6.1.0]

### Added
- `rules/common_word_fixes.yaml` and
  `rules/known_suspicious_candidates.yaml`: the previously hardcoded
  `COMMON_WORD_FIXES` / `KNOWN_SUSPICIOUS_CANDIDATES` Python dicts
  extracted to data files (byte-for-byte verified against the
  originals at extraction time). `Dictionaries.load()` reads these,
  falling back to the built-in Python constants if absent (adding the
  YAML files is additive, never a hard requirement).
- `CommonWordFixList` / `suspicious.py` now read fix tables from
  `ctx.dictionaries` instead of module-level constants.

## [6.0.0]

Initial release of the refactored package, replacing the
`chechen-ocr-processor-main` standalone-script collection
(`process.py`, `process_text.py`, `normalize_palochka_final.py`,
`normalize_remaining_ocr_chars_v2.py`, `run_pipeline.py`,
`make_review_table_with_context.py`, `apply_review_table.py`, and
others in `src/`) with a single installable package built around a
`Corrector`/`Pipeline` architecture (Variant B from the refactor
proposal).

### Added
- `chechen_ocr/core.py`: `Correction`, `CorrectionResult`,
  `PipelineContext`, `Corrector` protocol, `Pipeline` — no module-level
  global state (replaces `CORRECTION_LOG`, `SUSPICIOUS_LOG`,
  `PALOCHKA_DICTIONARY` globals from the original scripts).
- `chechen_ocr/config.py` (`Settings`): paths, `tesseract_cmd`, Vision
  model config — replaces the hardcoded
  `C:\Program Files\Tesseract-OCR\tesseract.exe` path and the
  "rules/ relative to cwd" assumption in the original scripts.
- `chechen_ocr/dictionaries.py` (`Dictionaries`): loads
  `rules/*.txt` once per `rules_dir`, cached.
- `chechen_ocr/correctors/`: five correctors ported from the original
  scripts — `DirectPalochkaLookalikes`, `PatternBasedPalochka`,
  `CommonWordFixList`, `SingleCandidateDictionaryFix`,
  `RemainingCharsCleanup`.
- `chechen_ocr/ocr/`: `OcrEngine` protocol, `TesseractEngine`,
  `OpenAIVisionEngine` — decouples "get raw text from an image" from
  "clean up Chechen-specific OCR artifacts."
- `chechen_ocr/review/`: `build_review_rows`, `apply_review_rows` —
  ported from `make_review_table_with_context.py` /
  `apply_review_table.py`, same context-based safety checks.
- `chechen_ocr/io/`: `extract_docx_to_text`, `save_docx` (with
  suspicious-word highlighting) — ported from `run_pipeline.py` /
  `process.py`.
- `chechen_ocr/suspicious.py`: `detect_suspicious_words`.
- `chechen_ocr/processor.py` (`ChechenOcrProcessor`): the public API,
  plus `build_pipeline()`, which enables/disables Tesseract-specific
  correctors based on which `OcrEngine` produced the text.
- `chechen_ocr/cli.py`: `chechen-ocr-text`, `chechen-ocr-image`,
  `chechen-ocr-apply-review` entrypoints.
- `tests/`: unit tests per corrector/module using tiny synthetic
  dictionaries (not the full ~75k-word list), so they stay fast and
  independent of `rules/` content.
- `tests/golden/`: regression test against the manually-proofread
  reference (pages 11-73) — see `tests/golden/manual_resolutions.py`
  for the audited page-attribution fixes this uncovered along the way
  (misattributed scans originally recorded as "missing," true
  duplicate photos, page numbers recovered from the "номер не
  распознан" bucket).
- `.github/workflows/ci.yml`: lint (ruff) + type-check (mypy) + unit
  tests across Python 3.10/3.11/3.12 on every push/PR.
  Golden-file regression is intentionally NOT run in CI (needs the
  actual book text, excluded from the repo per data policy, and only
  exists locally) — run manually via `pytest tests/golden/ -v -m
  golden` before merging a change that touches the correction
  pipeline.
- `.pre-commit-config.yaml`: same lint/format/type/unit-test checks
  locally before each commit.

### Fixed
- Indentation bug in the original `generate_palochka_candidates`: a
  pair-replacement dict was accidentally rebuilt inside an unrelated
  loop due to a stray extra indent level. Harmless in practice
  (results deduplicated via a set) but wasteful and confusing; fixed
  as part of the port (see `correctors/dictionary_candidate.py`
  docstring).
