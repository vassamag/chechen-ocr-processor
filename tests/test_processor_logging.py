import logging

from chechen_ocr import ChechenOcrProcessor, Settings
from chechen_ocr.dictionaries import Dictionaries


def test_logs_info_summary_after_processing(caplog):
    processor = ChechenOcrProcessor(settings=Settings.default(), dictionaries=Dictionaries.empty())

    with caplog.at_level(logging.INFO, logger="chechen_ocr.processor"):
        processor.process_text("хӀара кӀант дела.")

    assert any("processed" in record.message for record in caplog.records)


def test_warns_when_suspicious_ratio_exceeds_threshold(caplog):
    settings = Settings(suspicious_ratio_warning_threshold=0.01)
    processor = ChechenOcrProcessor(settings=settings, dictionaries=Dictionaries.empty())

    with caplog.at_level(logging.WARNING, logger="chechen_ocr.processor"):
        # Not in any built-in fix table, so it survives correction and
        # reaches suspicious-word detection still containing '['.
        processor.process_text("фыва[длро")

    assert any(record.levelno == logging.WARNING for record in caplog.records)
    assert any("suspicious-word ratio" in record.message for record in caplog.records)


def test_no_warning_when_ratio_stays_below_threshold(caplog):
    # A single suspicious word out of one total word is a 100% ratio,
    # so the threshold must be set above 100% to genuinely exercise the
    # no-warning path with this input.
    settings = Settings(suspicious_ratio_warning_threshold=1.5)
    processor = ChechenOcrProcessor(settings=settings, dictionaries=Dictionaries.empty())

    with caplog.at_level(logging.WARNING, logger="chechen_ocr.processor"):
        processor.process_text("фыва[длро")

    assert not any(record.levelno == logging.WARNING for record in caplog.records)


def test_compute_metrics_matches_processed_document():
    processor = ChechenOcrProcessor(settings=Settings.default(), dictionaries=Dictionaries.empty())
    doc = processor.process_text("хӀара кӀант дела.")

    metrics = processor.compute_metrics(doc)

    assert metrics.total_words == len(doc.corrected_text.split())
    assert metrics.suspicious_count == len(doc.suspicious)
