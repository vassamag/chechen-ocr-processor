"""
test_gui_integration.py

Drives the real Tkinter App end-to-end (not mocked widgets) -- these
need an actual display. Locally that's whatever your desktop provides;
in a headless environment (CI, this test suite's normal run) there is
none, so these tests SKIP rather than fail, mirroring the golden-file
test's skip-if-data-missing pattern (see tests/golden/).

To run these explicitly in a headless environment:

    xvfb-run -a pytest tests/gui/test_gui_integration.py -v -m gui

Modal dialogs (messagebox.showinfo/showwarning/showerror) are monkey-
patched to no-ops for the duration of each test -- in real usage they
wait for a click, which would hang an automated test.
"""

from __future__ import annotations

import queue as queue_module
import time

import pytest

from chechen_ocr.gui.review_model import TREEVIEW_COLUMNS

pytestmark = pytest.mark.gui


def _tk_display_available() -> bool:
    try:
        import tkinter as tk
    except ImportError:
        return False
    try:
        root = tk.Tk()
        root.destroy()
        return True
    except Exception:
        return False


def _skip_if_no_display():
    if not _tk_display_available():
        pytest.skip(
            "No Tk display available -- this is expected in a headless environment "
            "without Xvfb. Run `xvfb-run -a pytest tests/gui/ -v -m gui` to exercise "
            "these tests."
        )


@pytest.fixture
def app(monkeypatch):
    _skip_if_no_display()

    import tkinter as tk
    import tkinter.messagebox as messagebox

    from chechen_ocr.gui.app import App

    monkeypatch.setattr(messagebox, "showinfo", lambda *a, **kw: None)
    monkeypatch.setattr(messagebox, "showwarning", lambda *a, **kw: None)
    monkeypatch.setattr(messagebox, "showerror", lambda *a, **kw: None)

    root = tk.Tk()
    application = App(root)
    yield application
    root.destroy()


def _wait_for_job(app, timeout: float = 15.0):
    from chechen_ocr.gui.processing import JobDone, LogMessage

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            msg = app._message_queue.get(timeout=0.2)
        except queue_module.Empty:
            continue
        if isinstance(msg, LogMessage):
            continue
        if isinstance(msg, JobDone):
            return msg
    raise TimeoutError("background job did not finish in time")


def test_process_single_text_file(app, tmp_path):
    test_file = tmp_path / "input.txt"
    test_file.write_text("Цхьа стаг вара, цуьнан цIе Аълбикин хилла.", encoding="utf-8")

    app.current_path = test_file
    app.is_batch = False
    app.process_button.config(state="normal")
    app.on_process()

    msg = _wait_for_job(app)
    assert msg.error is None
    app._on_job_done(msg)

    assert app.doc is not None
    assert "цӀе" in app.doc.corrected_text  # "цIе" (Latin I) corrected to canonical Ӏ
    assert len(app.tree.get_children()) >= 1


def test_status_bar_shows_completion_summary(app, tmp_path):
    test_file = tmp_path / "input.txt"
    test_file.write_text("Цхьа стаг вара, цуьнан цIе Аълбикин хилла.", encoding="utf-8")

    app.current_path = test_file
    app.is_batch = False
    app.process_button.config(state="normal")
    app.on_process()
    app._on_job_done(_wait_for_job(app))

    status_text = app.status_bar.cget("text")
    assert "Done" in status_text
    assert "correction" in status_text
    assert "flagged" in status_text


def test_page_column_populated_for_standalone_digit_marker_convention(app, tmp_path):
    # Matches the bold-digit-marker-per-page DOCX convention (bold
    # formatting itself doesn't survive plain-text extraction, but the
    # standalone digit line does -- see review/schema.py's fallback).
    test_file = tmp_path / "input.txt"
    test_file.write_text(
        "90\n\nЦхьа стаг вара, цуьнан цIе Аълбикин хилла.\n\n91\n\nВукхо дийцира.",
        encoding="utf-8",
    )

    app.current_path = test_file
    app.is_batch = False
    app.process_button.config(state="normal")
    app.on_process()
    app._on_job_done(_wait_for_job(app))

    assert len(app.tree.get_children()) >= 1
    assert app.review_model.items[0].row.page == "90"
    values = app.tree.item(app.tree.get_children()[0], "values")
    assert values[TREEVIEW_COLUMNS.index("page")] == "90"


def test_review_edit_and_apply(app, tmp_path):
    test_file = tmp_path / "input.txt"
    test_file.write_text("Цхьа стаг вара, цуьнан цIе Аълбикин хилла.", encoding="utf-8")

    app.current_path = test_file
    app.is_batch = False
    app.on_process()
    app._on_job_done(_wait_for_job(app))

    row_id = app.tree.get_children()[0]
    app.tree.selection_set(row_id)
    app.on_tree_select()
    app.decision_var.set("replace")
    app.replacement_var.set("Аьлбикин")
    app.on_save_row()

    item = app.review_model.find_by_id(row_id)
    assert item.decision == "replace"
    assert item.replacement == "Аьлбикин"

    app.on_apply_review()
    assert "Аьлбикин" in app.doc.corrected_text
    assert "Аълбикин" not in app.doc.corrected_text


def test_export_txt_docx_csv(app, tmp_path, monkeypatch):
    import tkinter.filedialog as filedialog

    test_file = tmp_path / "input.txt"
    test_file.write_text("Цхьа стаг вара, цуьнан цIе Аълбикин хилла.", encoding="utf-8")

    app.current_path = test_file
    app.is_batch = False
    app.on_process()
    app._on_job_done(_wait_for_job(app))

    out_txt = tmp_path / "out.txt"
    monkeypatch.setattr(filedialog, "asksaveasfilename", lambda **kw: str(out_txt))
    app.on_export_txt()
    assert out_txt.exists()
    assert out_txt.read_text(encoding="utf-8") == app.doc.corrected_text

    out_docx = tmp_path / "out.docx"
    monkeypatch.setattr(filedialog, "asksaveasfilename", lambda **kw: str(out_docx))
    app.on_export_docx()
    assert out_docx.exists()

    out_csv = tmp_path / "out.csv"
    monkeypatch.setattr(filedialog, "asksaveasfilename", lambda **kw: str(out_csv))
    app.on_export_review_csv()
    assert out_csv.exists()
    csv_content = out_csv.read_text(encoding="utf-8-sig")
    assert "Аълбикин" in csv_content


def test_batch_mode(app, tmp_path):
    batch_dir = tmp_path / "batch"
    batch_dir.mkdir()
    (batch_dir / "page1.txt").write_text("Цхьа стаг вара дела.", encoding="utf-8")
    (batch_dir / "page2.txt").write_text("до[учу фыва[длро секха[ад", encoding="utf-8")

    app.current_path = batch_dir
    app.is_batch = True
    app.on_process()

    msg = _wait_for_job(app)
    assert msg.error is None
    app._on_job_done(msg)

    assert app.batch_result is not None
    assert len(app.per_file_tree.get_children()) == 2


def test_processing_error_is_surfaced_not_raised(app, tmp_path):
    # A nonexistent path should produce a JobDone with an error, not
    # crash the background thread silently.
    app.current_path = tmp_path / "does_not_exist.txt"
    app.is_batch = False
    app.on_process()

    msg = _wait_for_job(app)
    assert msg.error is not None
    app._on_job_done(msg)  # must not raise


def test_corrected_text_tab_is_editable_and_saves(app, tmp_path):
    test_file = tmp_path / "input.txt"
    test_file.write_text("Цхьа стаг вара дела.", encoding="utf-8")

    app.current_path = test_file
    app.is_batch = False
    app.on_process()
    app._on_job_done(_wait_for_job(app))

    # The widget must be directly editable (no "state=disabled" left
    # over from the read-only Log/Metrics tabs).
    assert str(app.corrected_text["state"]) == "normal"

    # Simulate a manual fix that doesn't fit the single-word Suspicious
    # Words model (e.g. a dropped letter spanning a phrase boundary).
    app.corrected_text.delete("1.0", "end")
    app.corrected_text.insert("1.0", "Цхьа стаг вара, ша лаьцна дела.")
    app.on_save_corrected_text()

    assert app.doc.corrected_text == "Цхьа стаг вара, ша лаьцна дела."
    # Widget must remain editable after a save, not lock up.
    assert str(app.corrected_text["state"]) == "normal"


def test_corrected_text_stays_editable_after_apply_review(app, tmp_path):
    test_file = tmp_path / "input.txt"
    test_file.write_text("Цхьа стаг вара, цуьнан цIе Аълбикин хилла.", encoding="utf-8")

    app.current_path = test_file
    app.is_batch = False
    app.on_process()
    app._on_job_done(_wait_for_job(app))

    app.on_apply_review()

    # After apply_review's programmatic text update, the widget should
    # still accept direct typing (not left in a disabled state).
    assert str(app.corrected_text["state"]) == "normal"


def test_selecting_row_shows_context_with_highlighted_word(app, tmp_path):
    test_file = tmp_path / "input.txt"
    test_file.write_text("Цхьа стаг вара, цуьнан цIе Аълбикин хилла.", encoding="utf-8")

    app.current_path = test_file
    app.is_batch = False
    app.on_process()
    app._on_job_done(_wait_for_job(app))

    row_id = app.tree.get_children()[0]
    app.tree.selection_set(row_id)
    app.on_tree_select()

    context_content = app.context_text.get("1.0", "end-1c")
    assert "Аълбикин" in context_content
    # The flagged word must actually carry the highlight tag, not just
    # appear in the plain text.
    tagged_ranges = app.context_text.tag_ranges("flagged_word")
    assert len(tagged_ranges) > 0
    highlighted_text = app.context_text.get(tagged_ranges[0], tagged_ranges[1])
    assert highlighted_text == "Аълбикин"


def test_selecting_row_shows_candidate_buttons(app, tmp_path):
    from tkinter import ttk

    test_file = tmp_path / "input.txt"
    test_file.write_text("Цхьа стаг вара, цуьнан цIе Аълбикин хилла.", encoding="utf-8")

    app.current_path = test_file
    app.is_batch = False
    app.on_process()
    app._on_job_done(_wait_for_job(app))

    row_id = app.tree.get_children()[0]
    app.tree.selection_set(row_id)
    app.on_tree_select()

    buttons = [w for w in app.candidates_frame.winfo_children() if isinstance(w, ttk.Button)]
    assert len(buttons) >= 1
    assert any(b["text"] == "Аьлбикин" for b in buttons)


def test_clicking_candidate_button_fills_replacement_field(app, tmp_path):
    test_file = tmp_path / "input.txt"
    test_file.write_text("Цхьа стаг вара, цуьнан цIе Аълбикин хилла.", encoding="utf-8")

    app.current_path = test_file
    app.is_batch = False
    app.on_process()
    app._on_job_done(_wait_for_job(app))

    row_id = app.tree.get_children()[0]
    app.tree.selection_set(row_id)
    app.on_tree_select()

    app._select_candidate("Аьлбикин")
    assert app.replacement_var.get() == "Аьлбикин"


def test_selecting_unedited_row_prefills_replacement_with_top_candidate(app, tmp_path):
    # Raised via real-world usage: having to type (or even click a
    # button for) the suggested word every time was extra friction --
    # the common case is simply that the top candidate is correct.
    test_file = tmp_path / "input.txt"
    test_file.write_text("Цхьа стаг вара, цуьнан цIе Аълбикин хилла.", encoding="utf-8")

    app.current_path = test_file
    app.is_batch = False
    app.on_process()
    app._on_job_done(_wait_for_job(app))

    row_id = app.tree.get_children()[0]
    app.tree.selection_set(row_id)
    app.on_tree_select()

    # No click, no typing -- Replacement should already show the top
    # candidate the moment the row is selected.
    assert app.replacement_var.get() == "Аьлбикин"
    # Decision must NOT be auto-set to "replace" -- pre-filling a
    # suggestion is not the same as approving it.
    assert app.decision_var.get() == "pending"


def test_reselecting_edited_row_shows_saved_replacement_not_the_prefill(app, tmp_path):
    test_file = tmp_path / "input.txt"
    test_file.write_text("Цхьа стаг вара, цуьнан цIе Аълбикин хилла.", encoding="utf-8")

    app.current_path = test_file
    app.is_batch = False
    app.on_process()
    app._on_job_done(_wait_for_job(app))

    row_id = app.tree.get_children()[0]
    app.tree.selection_set(row_id)
    app.on_tree_select()
    app.decision_var.set("replace")
    app.replacement_var.set("совершенно другое слово")
    app.on_save_row()

    # Deselect, then reselect -- the previously SAVED replacement must
    # win over the candidate pre-fill.
    app.replacement_var.set("")
    app.on_tree_select()
    assert app.replacement_var.get() == "совершенно другое слово"


def test_context_panel_clears_when_new_document_processed(app, tmp_path):
    test_file = tmp_path / "input.txt"
    test_file.write_text("Цхьа стаг вара, цуьнан цIе Аълбикин хилла.", encoding="utf-8")

    app.current_path = test_file
    app.is_batch = False
    app.on_process()
    app._on_job_done(_wait_for_job(app))

    row_id = app.tree.get_children()[0]
    app.tree.selection_set(row_id)
    app.on_tree_select()

    # Process a clean file with no suspicious words -- the stale
    # context from the previous file must not linger.
    clean_file = tmp_path / "clean.txt"
    clean_file.write_text("хӀара кӀант дела.", encoding="utf-8")
    app.current_path = clean_file
    app.on_process()
    app._on_job_done(_wait_for_job(app))

    assert "Аълбикин" not in app.context_text.get("1.0", "end-1c")


def test_suspicious_word_is_highlighted_in_corrected_text_after_processing(app, tmp_path):
    test_file = tmp_path / "input.txt"
    test_file.write_text("Цхьа стаг вара, цуьнан цIе Аълбикин хилла.", encoding="utf-8")

    app.current_path = test_file
    app.is_batch = False
    app.on_process()
    app._on_job_done(_wait_for_job(app))

    from chechen_ocr.gui.app import SUSPICIOUS_TAG

    ranges = app.corrected_text.tag_ranges(SUSPICIOUS_TAG)
    assert len(ranges) > 0
    highlighted = app.corrected_text.get(ranges[0], ranges[1])
    assert highlighted == "Аълбикин"


def test_applied_word_is_highlighted_green_after_apply_review(app, tmp_path):
    test_file = tmp_path / "input.txt"
    test_file.write_text("Цхьа стаг вара, цуьнан цIе Аълбикин хилла.", encoding="utf-8")

    app.current_path = test_file
    app.is_batch = False
    app.on_process()
    app._on_job_done(_wait_for_job(app))

    row_id = app.tree.get_children()[0]
    app.tree.selection_set(row_id)
    app.on_tree_select()
    app.decision_var.set("replace")
    app.replacement_var.set("Аьлбикин")
    app.on_save_row()
    app.on_apply_review()

    from chechen_ocr.gui.app import APPLIED_TAG, SUSPICIOUS_TAG

    applied_ranges = app.corrected_text.tag_ranges(APPLIED_TAG)
    assert len(applied_ranges) > 0
    assert app.corrected_text.get(applied_ranges[0], applied_ranges[1]) == "Аьлбикин"

    # The word was resolved -- it should no longer carry the "still
    # flagged" (yellow) tag.
    pending_ranges = app.corrected_text.tag_ranges(SUSPICIOUS_TAG)
    assert len(pending_ranges) == 0


def test_unresolved_word_stays_highlighted_after_partial_apply(app, tmp_path):
    test_file = tmp_path / "input.txt"
    test_file.write_text(
        "Цхьа стаг вара, цуьнан цIе Аълбикин хилла. до[учу фыва[длро", encoding="utf-8"
    )

    app.current_path = test_file
    app.is_batch = False
    app.on_process()
    app._on_job_done(_wait_for_job(app))

    # Resolve only one of the (at least) two flagged words, leave the
    # rest pending, then apply.
    first_row_id = app.tree.get_children()[0]
    app.tree.selection_set(first_row_id)
    app.on_tree_select()
    app.decision_var.set("replace")
    app.replacement_var.set("исправлено")
    app.on_save_row()
    app.on_apply_review()

    from chechen_ocr.gui.app import SUSPICIOUS_TAG

    # At least one still-unresolved flagged word must remain highlighted.
    assert len(app.corrected_text.tag_ranges(SUSPICIOUS_TAG)) > 0


def test_suspicious_words_table_rows_have_alternating_tags(app, tmp_path):
    # Raised via real-world usage: rows/columns in the Suspicious Words
    # table had no visual separation at all -- alternating row colors
    # were added to fix that. Verify the tags are actually applied,
    # not just configured and unused.
    test_file = tmp_path / "input.txt"
    test_file.write_text(
        "до[учу текст. фыва[длро текст. секха[ад текст. лаьхи[адр текст.",
        encoding="utf-8",
    )

    app.current_path = test_file
    app.is_batch = False
    app.on_process()
    app._on_job_done(_wait_for_job(app))

    row_ids = app.tree.get_children()
    assert len(row_ids) >= 2

    tags_seen = {app.tree.item(row_id, "tags")[0] for row_id in row_ids[:2]}
    assert tags_seen == {"evenrow", "oddrow"}


def test_review_session_survives_a_reprocess_after_manual_edit(app, tmp_path):
    # End-to-end version of the item-10 design ("половина страницы
    # отредактирована, половина нет") -- Process, manually edit part
    # of the Corrected Text box, Save Edits, Process again, and check
    # the edit is still there while an untouched line got refreshed.
    test_file = tmp_path / "input.txt"
    test_file.write_text("90\n\nцIе биъ\nхIара кIант", encoding="utf-8")

    app.current_path = test_file
    app.is_batch = False
    app.ocr_engine_var.set("openai_vision")
    app.process_button.config(state="normal")
    app.on_process()
    app._on_job_done(_wait_for_job(app))

    assert app.review_session is not None
    session_file = test_file.with_suffix(test_file.suffix + ".review_session.json")
    assert session_file.exists()

    # Manually edit just the first line, leave the second untouched.
    edited_text = app.doc.corrected_text.replace("цӀе биъ", "цӀе биъ (правка вручную)")
    app.corrected_text.configure(state="normal")
    app.corrected_text.delete("1.0", "end")
    app.corrected_text.insert("1.0", edited_text)
    app.on_save_corrected_text()

    assert app.review_session.blocks[0].lines[0].is_edited is True

    # Re-process the same file -- the edit must survive untouched.
    app.on_process()
    app._on_job_done(_wait_for_job(app))

    assert "цӀе биъ (правка вручную)" in app.doc.corrected_text
    # the untouched second line should still be present, refreshed by
    # the corrector (хIара -> хӀара via the always-on homoglyph fix)
    assert "хӀара кӀант" in app.doc.corrected_text
