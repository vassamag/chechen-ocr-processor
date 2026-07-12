# Migrating vassamag/chechen-ocr-processor to this refactor

Tailored to the repo's actual current structure (`docs/`, `rules/`,
`src/`, `.gitignore`, `README.md`, `requirements.txt` on `main`, 0 tags).

## 1. Clone and branch

```bash
git clone https://github.com/vassamag/chechen-ocr-processor.git
cd chechen-ocr-processor
git checkout -b refactor/v6-corrector-pipeline
```

## 2. Move the old scripts out of the way

The new `chechen_ocr/` package replaces everything in `src/`. Don't
delete it outright — move it to `legacy/` so git history stays intact
and you can still diff against the original logic if needed:

```bash
mkdir -p legacy
git mv src legacy/src
```

`docs/` can stay as-is (historical status reports like
`OCR_PROCESSOR_V5_4_FINAL_STATUS.md` are still useful context — the
new `CHANGELOG.md` references it directly).

## 3. Merge `rules/`, don't overwrite it

Your existing `rules/` already has `palochka_words.txt`,
`chechen_words.txt`, `chechen_phrases.txt` — this refactor's `rules/`
adds two NEW files (`common_word_fixes.yaml`,
`known_suspicious_candidates.yaml`) alongside them. Copy this
refactor's `rules/*.yaml` into your existing `rules/` directory; the
`.txt` files should be identical (byte-for-byte, since that's where
they originally came from) but diff them to be sure:

```bash
diff legacy/../rules/palochka_words.txt <path-to-this-refactor>/rules/palochka_words.txt
```

## 4. Copy in the new package

From this refactor's root, copy everything except `tests/golden/data/`
(never commit that — see its own `.gitignore`) into the repo root:

```bash
cp -r chechen_ocr/ /path/to/chechen-ocr-processor/
cp -r tests/ /path/to/chechen-ocr-processor/          # tests/golden/data/ stays empty (gitignored)
cp -r .github/ /path/to/chechen-ocr-processor/
cp pyproject.toml requirements.txt .pre-commit-config.yaml .gitignore CHANGELOG.md /path/to/chechen-ocr-processor/
# merge README.md by hand rather than overwrite -- your existing one may have
# project-specific notes worth keeping alongside this refactor's additions
```

## 5. Commit and open a PR

```bash
git add -A
git commit -m "Refactor to Corrector/Pipeline package architecture (v6.0.0-v6.5.0)

See CHANGELOG.md for the full version-by-version history.
Old scripts moved to legacy/src/ for reference."
git push -u origin refactor/v6-corrector-pipeline
```

Open the PR on GitHub (`refactor/v6-corrector-pipeline` → `main`) even
as a solo maintainer — CI (`.github/workflows/ci.yml`) will run
automatically, and the PR gives you one link that shows the entire
before/after diff.

## 6. Merge, then tag

```bash
git checkout main
git pull
git merge --no-ff refactor/v6-corrector-pipeline
git push

git tag -a v6.5.0 -m "Refactor to Corrector/Pipeline architecture; see CHANGELOG.md"
git push origin v6.5.0
```

## 7. Going forward

- Bump `chechen_ocr/__init__.py`'s `__version__` for any release-worthy
  change (`pyproject.toml`'s version is read from it automatically —
  see `[tool.setuptools.dynamic]` — so there's only one place to edit).
- Add an entry to `CHANGELOG.md` under a new version heading.
- Tag the commit: `git tag -a vX.Y.Z -m "..." && git push origin vX.Y.Z`.
- Since the repo is private and this is a single-maintainer project,
  there's no need for a PyPI publish step — `pip install -e .` from a
  local clone (or `pip install git+https://github.com/vassamag/chechen-ocr-processor.git@vX.Y.Z`
  for a pinned install elsewhere) is enough.
