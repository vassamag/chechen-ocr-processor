#!/usr/bin/env python3
"""
manual_resolutions.py

Hand-verified fixes for page-attribution problems in the raw OCR dump
`recognized_text_ordered.txt`, discovered while building the golden-file
harness for pages 11-73.

Root cause (per project owner): some phone-photo scans captured part of
a NEIGHBORING page, or the printed page number wasn't visible in the
photo at all. Two distinct failure modes followed from that:

  1. The photo's number wasn't visible/readable at all -> OCR filed the
     block under "Страница номер не распознан" (page=None).
  2. The photo's number WAS read, but as the WRONG number -- landing it
     as an apparent "duplicate" of some other, unrelated page.

Both cases are fixed the same way: PAGE_NUMBER_OVERRIDES maps a
filename to its hand-verified TRUE page number, overriding whatever
parse_raw_ocr.py parsed (None or a wrong number) for that file.

Each entry was verified by:
  1. Fuzzy word-level matching (difflib.SequenceMatcher.quick_ratio)
     of the raw block's text against the manually-proofread reference
     for the candidate page and its immediate neighbors (N-1, N, N+1).
  2. For pages 24 and 33: the project owner supplied the original scan
     photos directly, confirming both the printed page number visible
     in the image and a near-verbatim text match against the manual
     proofread reference.

This table is data, not logic -- if the raw OCR source file changes
(re-scanned, more photos added), re-verify these entries before
trusting them again.
"""

from __future__ import annotations

# filename -> hand-verified true page number, overriding whatever
# parse_raw_ocr.py parsed for that file (None, or a wrong number it
# happened to share with another, unrelated photo).
PAGE_NUMBER_OVERRIDES: dict[str, int] = {
    # Landed in "номер не распознан" (page not visible in photo);
    # content verified to match these pages almost verbatim.
    "IMG-20251222-WA0048.jpg": 50,  # verified: quick_ratio 0.837 vs page 50
    "IMG-20251222-WA0036.jpg": 54,  # verified: quick_ratio 0.817 vs page 54
    # Originally parsed as page 19 (sharing that number with the real
    # page-19 photo, IMG-20250825-WA0025.jpg) -- confirmed via the
    # original scan photo to actually be page 24 (visible printed page
    # number, and text matches the manual reference almost verbatim).
    "IMG-20250826-WA0010.jpg": 24,
    # Originally parsed as page 31 (sharing that number with
    # IMG-20251222-WA0025.jpg, itself a genuine but partial/incomplete
    # photo of page 31) -- confirmed via the original scan photo to
    # actually be page 33.
    "IMG-20251222-WA0034.jpg": 33,
}

# Pages where, even after PAGE_NUMBER_OVERRIDES is applied, more than
# one block remains under the same page number. Two different reasons
# land an entry here -- see each comment:
#   - true duplicate/retake: BOTH blocks verified to match that page's
#     text well (pick either, content is equivalent).
#   - unresolved stray: one block is verified correct; the other's true
#     page is still unknown/unidentified (not a match for this page or
#     its neighbors) and is simply excluded, same as a true duplicate
#     would be, but for a different reason.
PREFERRED_BLOCK_FOR_TRUE_DUPLICATE: dict[int, str] = {
    21: "IMG-20250825-WA0026.jpg",  # true duplicate: both ~0.84/0.80 vs page 21
    27: "IMG-20250826-WA0008.jpg",  # true duplicate: both ~0.836 vs page 27 (tie, arbitrary pick)
    32: "IMG-20251222-WA0026.jpg",  # true duplicate: both ~0.82 vs page 32 (tie, arbitrary pick)
    69: "IMG-20251222-WA0068.jpg",  # unresolved stray: verified match 0.888; other block (WA0145.jpg) doesn't match page 69 or its neighbors -- true page unknown
}

# Still genuinely unaccounted for. Originally two pages (24, 33) were
# in this list -- both resolved above once the project owner supplied
# the original photos and the misattribution was confirmed visually.
STILL_MISSING_PAGES: list[int] = []
