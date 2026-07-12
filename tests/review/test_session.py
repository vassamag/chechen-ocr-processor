from __future__ import annotations

from pathlib import Path

from chechen_ocr import ChechenOcrProcessor, Settings
from chechen_ocr.dictionaries import Dictionaries
from chechen_ocr.review.session import (
    BlockRecord,
    LineRecord,
    ReviewSession,
    build_session_from_blocks,
    build_session_from_text,
    reprocess_session,
    session_path_for,
    split_text_into_blocks,
    sync_session_with_edited_text,
)


def _make_processor() -> ChechenOcrProcessor:
    return ChechenOcrProcessor(
        settings=Settings.default(),
        dictionaries=Dictionaries.empty(),
    )


def test_line_record_is_edited_reflects_whether_saved_differs_from_corrector_output():
    unedited = LineRecord(corrector_output="хӀара кӀант", saved_text="хӀара кӀант")
    edited = LineRecord(corrector_output="хӀара кӀант", saved_text="хӀара жима кӀант")

    assert unedited.is_edited is False
    assert edited.is_edited is True


def test_block_text_joins_saved_text_of_every_line():
    block = BlockRecord(
        block_id="1",
        lines=[
            LineRecord(corrector_output="цхьа", saved_text="цхьа"),
            LineRecord(corrector_output="шиъ", saved_text="кхаа"),  # edited
        ],
    )

    assert block.text == "цхьа\nкхаа"


def test_block_has_any_edits_true_only_when_some_line_differs():
    unedited_block = BlockRecord(
        block_id="1",
        lines=[LineRecord(corrector_output="цхьа", saved_text="цхьа")],
    )
    edited_block = BlockRecord(
        block_id="2",
        lines=[LineRecord(corrector_output="цхьа", saved_text="кхаа")],
    )

    assert unedited_block.has_any_edits is False
    assert edited_block.has_any_edits is True


def test_build_session_from_blocks_starts_fully_unedited():
    session = build_session_from_blocks([("page_001.jpg", "цхьа стаг\nвара")])

    block = session.blocks[0]
    assert block.block_id == "page_001.jpg"
    assert all(not line.is_edited for line in block.lines)
    assert block.text == "цхьа стаг\nвара"


def test_block_identity_is_position_or_filename_not_page_number():
    # Block identity must be independent of the (possibly wrong or
    # missing) page number -- page_number/page_verified are a
    # separate field, not tied to block_id.
    session = build_session_from_blocks([("IMG-0042.jpg", "текст")])
    block = session.blocks[0]
    block.page_number = "?"  # unrecognized page number
    block.page_verified = False

    # block_id still resolves the block correctly, independent of the
    # (unverified/missing) page number
    assert session.find_block("IMG-0042.jpg") is block


def test_find_block_returns_none_for_unknown_id():
    session = build_session_from_blocks([("a", "text")])

    assert session.find_block("nonexistent") is None


def test_save_and_load_roundtrip_preserves_everything(tmp_path):
    session = build_session_from_blocks([("page1", "цхьа\nшиъ"), ("page2", "кхаа")])
    session.blocks[0].lines[1].saved_text = "ши"  # simulate a human edit
    session.blocks[0].page_number = "11"
    session.blocks[0].page_verified = True
    session.last_position = ("page1", 1)

    path = tmp_path / "output.docx.review_session.json"
    session.save(path)
    loaded = ReviewSession.load(path)

    assert loaded.blocks[0].block_id == "page1"
    assert loaded.blocks[0].lines[1].saved_text == "ши"
    assert loaded.blocks[0].lines[1].is_edited is True
    assert loaded.blocks[0].page_number == "11"
    assert loaded.blocks[0].page_verified is True
    assert loaded.last_position == ("page1", 1)


def test_session_path_for_uses_a_sidecar_not_the_document_itself():
    output = Path("combined_11_236.docx")

    path = session_path_for(output)

    assert path.name == "combined_11_236.docx.review_session.json"
    assert path != output


def test_reprocess_session_refreshes_unedited_lines():
    session = build_session_from_blocks([("page1", "цIе Аълбикин")])
    processor = _make_processor()

    result = reprocess_session(session, processor, ocr_engine_name="openai_vision")

    # "цIе" (Latin I) should get corrected to canonical Ӏ by the
    # always-on homoglyph corrector, since the line was never edited.
    assert "цӀе" in result.blocks[0].text


def test_reprocess_session_leaves_edited_lines_completely_untouched():
    session = build_session_from_blocks([("page1", "цIе Аълбикин")])
    # Simulate a human edit that intentionally keeps the "wrong" Latin I --
    # maybe they know something the corrector doesn't for this specific case.
    session.blocks[0].lines[0].saved_text = "цIе Аълбикин (проверено вручную)"
    processor = _make_processor()

    result = reprocess_session(session, processor, ocr_engine_name="openai_vision")

    assert result.blocks[0].lines[0].saved_text == "цIе Аълбикин (проверено вручную)"


def test_reprocess_session_preserves_last_position():
    session = build_session_from_blocks([("page1", "текст")])
    session.last_position = ("page1", 0)
    processor = _make_processor()

    result = reprocess_session(session, processor, ocr_engine_name="openai_vision")

    assert result.last_position == ("page1", 0)


def test_reprocess_session_can_partially_lock_a_block():
    # The exact scenario raised in project discussion: half a page
    # edited, half not -- each line tracked independently within the
    # same block.
    session = build_session_from_blocks([("page1", "цIе биъ\nхIара кIант")])
    session.blocks[0].lines[0].saved_text = "цIе биъ (edited, kept as-is)"
    processor = _make_processor()

    result = reprocess_session(session, processor, ocr_engine_name="openai_vision")

    lines = result.blocks[0].lines
    assert lines[0].saved_text == "цIе биъ (edited, kept as-is)"  # untouched
    assert lines[1].saved_text != "хIара кIант"  # refreshed by the corrector


def test_split_text_into_blocks_uses_service_header_format():
    text = "===== Страница 11 | a.jpg =====\n\nтекст 1\n===== Страница 12 | b.jpg =====\n\nтекст 2"

    chunks = split_text_into_blocks(text)

    assert len(chunks) == 2
    block_id, page_number, block_text = chunks[0]
    assert block_id == "0"  # ordinal position, NOT the page number
    assert page_number == "11"
    assert "текст 1" in block_text


def test_split_text_into_blocks_falls_back_to_standalone_digit_lines():
    text = "90\n\nтекст страницы 90\n\n91\n\nтекст страницы 91"

    chunks = split_text_into_blocks(text)

    assert len(chunks) == 2
    assert chunks[0][1] == "90"
    assert chunks[1][1] == "91"


def test_split_text_into_blocks_treats_whole_text_as_one_block_when_no_markers():
    text = "просто текст без разметки страниц"

    chunks = split_text_into_blocks(text)

    assert len(chunks) == 1
    assert chunks[0][0] == "0"
    assert chunks[0][1] == ""  # no page number detected
    assert chunks[0][2] == text


def test_build_session_from_text_matches_split_text_into_blocks():
    text = "90\n\nцхьа стаг\n\n91\n\nвукхо дийцира"

    session = build_session_from_text(text)

    assert len(session.blocks) == 2
    assert session.blocks[0].page_number == "90"
    assert session.blocks[0].text == "цхьа стаг"
    assert all(not line.is_edited for block in session.blocks for line in block.lines)


def test_sync_session_with_edited_text_updates_matching_line_counts():
    session = build_session_from_text("90\n\nцхьа стаг\nвара")
    edited_text = "90\n\nцхьа стаг\nвара (правка)"

    result = sync_session_with_edited_text(session, edited_text)

    assert result.blocks[0].lines[0].is_edited is False  # unchanged line stays unedited
    assert result.blocks[0].lines[1].is_edited is True  # edited line is now flagged
    assert result.blocks[0].lines[1].saved_text == "вара (правка)"


def test_sync_session_with_edited_text_locks_whole_block_when_line_count_changes():
    session = build_session_from_text("90\n\nцхьа стаг\nвара")
    # human added an extra line -- 1:1 line correspondence can no
    # longer be inferred reliably
    edited_text = "90\n\nцхьа стаг\nвара\nновая строка добавлена вручную"

    result = sync_session_with_edited_text(session, edited_text)

    assert len(result.blocks[0].lines) == 1
    assert result.blocks[0].lines[0].is_edited is True
    assert "новая строка" in result.blocks[0].lines[0].saved_text


def test_sync_session_with_edited_text_preserves_block_removed_from_edited_text():
    session = build_session_from_text("90\n\nстр девяносто\n\n91\n\nстр девяносто один")
    # human deleted page 91's marker+content entirely from the text box
    edited_text = "90\n\nстр девяносто"

    result = sync_session_with_edited_text(session, edited_text)

    assert len(result.blocks) == 2  # block 91 preserved, not silently dropped
    assert result.blocks[1].page_number == "91"
