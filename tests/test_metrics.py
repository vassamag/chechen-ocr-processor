from chechen_ocr.core import Correction
from chechen_ocr.metrics import compute_metrics


def test_counts_words_and_corrections_by_rule():
    corrections = [
        Correction(rule="palochka_direct", before="I", after="Ӏ"),
        Correction(rule="palochka_direct", before="i", after="Ӏ"),
        Correction(rule="common_word_fix", before="хТара", after="хӀара"),
    ]

    metrics = compute_metrics("хӀара кӀант дела", corrections, suspicious_count=0)

    assert metrics.total_words == 3
    assert metrics.total_corrections == 3
    assert metrics.corrections_by_rule == {"palochka_direct": 2, "common_word_fix": 1}


def test_suspicious_ratio_is_fraction_of_total_words():
    metrics = compute_metrics("одно два три четыре", corrections=[], suspicious_count=1)
    assert metrics.suspicious_ratio == 0.25


def test_empty_text_does_not_divide_by_zero():
    metrics = compute_metrics("", corrections=[], suspicious_count=0)
    assert metrics.total_words == 0
    assert metrics.suspicious_ratio == 0.0
    assert metrics.corrections_per_1000_words == 0.0


def test_unconverted_lookalikes_are_detected():
    # "zzz1zzz" has a digit-1 lookalike and no palochka -- should count.
    # "хӀара" has a real palochka -- should NOT count even though it's
    # otherwise similar in shape. "word" contains none of the lookalike
    # characters (I, i, l, 1, |, !, [, ], Ї, ї, Ј, ј) at all.
    metrics = compute_metrics("zzz1zzz хӀара word", corrections=[], suspicious_count=0)
    assert metrics.unconverted_lookalike_count == 1


def test_corrections_per_1000_words_scales_correctly():
    corrections = [Correction(rule="r", before="a", after="b") for _ in range(5)]
    text = " ".join(["word"] * 100)  # 100 words

    metrics = compute_metrics(text, corrections, suspicious_count=0)

    assert metrics.corrections_per_1000_words == 50.0
