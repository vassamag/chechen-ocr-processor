from chechen_ocr.review.build_review_table import build_review_rows
from chechen_ocr.suspicious import SuspiciousWord


def test_builds_one_row_per_suspicious_word():
    raw_text = "Цхьа стаг вара, Аълбикин хилла, дика стаг вара иза."
    corrected_text = raw_text  # word was left untouched (ambiguous/known-pattern case)
    suspicious = [
        SuspiciousWord(word="Аълбикин", reason="known OCR pattern", candidates=["Аьлбикин"])
    ]

    rows = build_review_rows(raw_text, corrected_text, suspicious)

    assert len(rows) == 1
    row = rows[0]
    assert row.word == "Аълбикин"
    assert row.reason == "known OCR pattern"
    assert row.candidates == "Аьлбикин"
    assert "[[Аълбикин]]" in row.raw_context
    assert "[[Аълбикин]]" in row.corrected_context
    assert row.decision == "pending"
    assert row.replacement == ""


def test_extracts_page_and_image_from_service_headers():
    raw_text = "===== Страница 11 | IMG-0001.jpg =====\n\nЦхьа Аълбикин хилла."
    corrected_text = raw_text
    suspicious = [SuspiciousWord(word="Аълбикин", reason="known OCR pattern", candidates=[])]

    rows = build_review_rows(raw_text, corrected_text, suspicious)

    assert rows[0].page == "11"
    assert rows[0].image_file == "IMG-0001.jpg"


def test_extracts_page_from_standalone_digit_line_fallback():
    # DOCX files using the bold-digit-marker-per-page convention (e.g.
    # combined_11_236_one_page_per_sheet.docx) lose the bold formatting
    # once flattened to plain text by io/docx_reader.py, but the
    # standalone number line itself survives -- this is the fallback
    # that should pick it up when no "===== Страница =====" headers
    # are present at all.
    raw_text = "90\n\nЦхьа Аълбикин хилла.\n\n91\n\nВукхо дийцира."
    corrected_text = raw_text
    suspicious = [SuspiciousWord(word="Аълбикин", reason="known OCR pattern", candidates=[])]

    rows = build_review_rows(raw_text, corrected_text, suspicious)

    assert rows[0].page == "90"


def test_word_not_found_anywhere_is_noted():
    raw_text = "Цхьа стаг вара."
    corrected_text = raw_text
    suspicious = [SuspiciousWord(word="totallyabsentword", reason="test", candidates=[])]

    rows = build_review_rows(raw_text, corrected_text, suspicious)

    assert rows[0].raw_context == ""
    assert rows[0].corrected_context == ""
    assert "context not found" in rows[0].notes


def test_sequential_search_advances_past_first_occurrence():
    # Two suspicious entries with the same word text should each get
    # matched to a DIFFERENT occurrence, not both to the first one.
    raw_text = "Аълбикин ву цигахь. Аълбикин ву кхузахь а."
    corrected_text = raw_text
    suspicious = [
        SuspiciousWord(word="Аълбикин", reason="r", candidates=[]),
        SuspiciousWord(word="Аълбикин", reason="r", candidates=[]),
    ]

    rows = build_review_rows(raw_text, corrected_text, suspicious)

    assert rows[0].raw_context != rows[1].raw_context
