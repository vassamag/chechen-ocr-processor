import queue
import time

from chechen_ocr.gui.processing import JobDone, LogMessage, QueueLogHandler, run_in_background
from chechen_ocr.gui.review_model import EditableReviewRow, ReviewTableModel
from chechen_ocr.review.schema import ReviewRow


def test_run_in_background_puts_result_on_success():
    q: queue.Queue = queue.Queue()
    run_in_background(lambda: 42, q)

    msg = q.get(timeout=5)
    assert isinstance(msg, JobDone)
    assert msg.result == 42
    assert msg.error is None


def test_run_in_background_puts_error_on_exception():
    q: queue.Queue = queue.Queue()

    def fail():
        raise ValueError("boom")

    run_in_background(fail, q)

    msg = q.get(timeout=5)
    assert isinstance(msg, JobDone)
    assert msg.result is None
    assert isinstance(msg.error, ValueError)
    assert str(msg.error) == "boom"


def test_run_in_background_does_not_block_caller():
    q: queue.Queue = queue.Queue()
    started = time.time()

    def slow():
        time.sleep(0.3)
        return "done"

    run_in_background(slow, q)
    elapsed = time.time() - started

    assert elapsed < 0.1  # returns immediately, doesn't wait for the thread
    msg = q.get(timeout=5)
    assert msg.result == "done"


def test_queue_log_handler_pushes_formatted_records():
    import logging

    q: queue.Queue = queue.Queue()
    handler = QueueLogHandler(q)
    handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))

    logger = logging.getLogger("test_queue_log_handler")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.info("hello world")

    msg = q.get(timeout=1)
    assert isinstance(msg, LogMessage)
    assert "hello world" in msg.text
    assert msg.level == logging.INFO

    logger.removeHandler(handler)


def _make_review_row(row_id: int, word: str) -> ReviewRow:
    return ReviewRow(id=row_id, word=word, reason="test reason", candidates="cand1, cand2")


def test_review_table_model_from_rows():
    rows = [_make_review_row(1, "foo"), _make_review_row(2, "bar")]
    model = ReviewTableModel.from_rows(rows)

    assert len(model.items) == 2
    assert all(isinstance(item, EditableReviewRow) for item in model.items)
    assert all(item.decision == "pending" for item in model.items)


def test_find_by_id():
    model = ReviewTableModel.from_rows([_make_review_row(1, "foo"), _make_review_row(2, "bar")])

    found = model.find_by_id("2")
    assert found is not None
    assert found.row.word == "bar"

    assert model.find_by_id("999") is None


def test_set_decision_and_replacement():
    model = ReviewTableModel.from_rows([_make_review_row(1, "foo")])

    model.set_decision("1", "replace")
    model.set_replacement("1", "corrected_foo")

    item = model.find_by_id("1")
    assert item.decision == "replace"
    assert item.replacement == "corrected_foo"


def test_set_decision_rejects_invalid_value():
    import pytest

    model = ReviewTableModel.from_rows([_make_review_row(1, "foo")])
    with pytest.raises(ValueError, match="Invalid decision"):
        model.set_decision("1", "not_a_real_decision")


def test_pending_count():
    model = ReviewTableModel.from_rows(
        [_make_review_row(1, "foo"), _make_review_row(2, "bar"), _make_review_row(3, "baz")]
    )
    model.set_decision("1", "replace")
    model.set_decision("2", "reject")

    assert model.pending_count() == 1


def test_as_apply_dicts_reflects_edits():
    model = ReviewTableModel.from_rows([_make_review_row(1, "foo")])
    model.set_decision("1", "replace")
    model.set_replacement("1", "bar")

    dicts = model.as_apply_dicts()

    assert len(dicts) == 1
    assert dicts[0]["decision"] == "replace"
    assert dicts[0]["replacement"] == "bar"
    assert dicts[0]["word"] == "foo"


def test_display_values_reflects_current_state():
    model = ReviewTableModel.from_rows([_make_review_row(1, "foo")])
    item = model.items[0]

    assert item.display_values()[0] == "1"
    assert item.display_values()[2] == "foo"
    assert item.display_values()[5] == "pending"

    model.set_decision("1", "reject")
    assert item.display_values()[5] == "reject"
