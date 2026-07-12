from chechen_ocr.review.apply_review_table import apply_review_rows


def test_applies_replace_decision_via_context():
    text = "Цхьа стаг вара, Аълбикин хилла."
    rows = [
        {
            "id": "1",
            "word": "Аълбикин",
            "replacement": "Аьлбикин",
            "corrected_context": "Цхьа стаг вара, [[Аълбикин]] хилла.",
            "decision": "replace",
        }
    ]

    new_text, results = apply_review_rows(text, rows)

    assert new_text == "Цхьа стаг вара, Аьлбикин хилла."
    assert results[0].status == "applied"


def test_pending_decision_is_not_considered():
    text = "Цхьа Аълбикин хилла."
    rows = [
        {
            "id": "1",
            "word": "Аълбикин",
            "replacement": "Аьлбикин",
            "corrected_context": "Цхьа [[Аълбикин]] хилла.",
            "decision": "pending",
        }
    ]

    new_text, results = apply_review_rows(text, rows)

    assert new_text == text
    assert results[0].status == "not_considered"


def test_reject_decision_is_not_applied():
    text = "Цхьа Аълбикин хилла."
    rows = [
        {
            "id": "1",
            "word": "Аълбикин",
            "replacement": "Аьлбикин",
            "corrected_context": "Цхьа [[Аълбикин]] хилла.",
            "decision": "reject",
        }
    ]

    new_text, results = apply_review_rows(text, rows)

    assert new_text == text
    assert results[0].status == "not_considered"


def test_replace_with_empty_replacement_is_skipped():
    text = "Цхьа Аълбикин хилла."
    rows = [
        {
            "id": "1",
            "word": "Аълбикин",
            "replacement": "",
            "corrected_context": "Цхьа [[Аълбикин]] хилла.",
            "decision": "replace",
        }
    ]

    new_text, results = apply_review_rows(text, rows)

    assert new_text == text
    assert results[0].status == "skipped"
    assert results[0].detail == "replace_with_empty_replacement"


def test_context_not_found_is_skipped_not_applied_blindly():
    text = "Цхьа Аълбикин хилла."
    rows = [
        {
            "id": "1",
            "word": "Аълбикин",
            "replacement": "Аьлбикин",
            "corrected_context": "This context does not exist in the text [[Аълбикин]] at all.",
            "decision": "replace",
        }
    ]

    new_text, results = apply_review_rows(text, rows)

    assert new_text == text
    assert results[0].status == "skipped"
    assert results[0].detail == "context_not_found"


def test_applies_when_real_text_has_hard_line_wraps_but_context_was_normalized():
    # Found via real-world usage: build_review_table.py normalizes
    # whitespace when building the context snippet, but a source text
    # with hard line-wrapped print paragraphs (a printed line per text
    # line) still has real newlines in the actual document -- an exact
    # substring match on the normalized context then fails even though
    # the word is right there. This must still apply, not just get
    # detected-and-skipped.
    text = "кадечу\nбТаьхоша хӀаллакбина. Царах цхьаъ дийна висина."
    rows = [
        {
            "id": "1",
            "word": "бТаьхоша",
            "replacement": "бӀаьхоша",
            # Context as build_review_table.py would produce it: real
            # newline collapsed to a single space.
            "corrected_context": "кадечу [[бТаьхоша]] хӀаллакбина.",
            "decision": "replace",
        }
    ]

    new_text, results = apply_review_rows(text, rows)

    assert "бӀаьхоша" in new_text
    assert "бТаьхоша" not in new_text
    # The real newline in the document must be preserved, not
    # collapsed to a space as a side effect of the match.
    assert "кадечу\nбӀаьхоша" in new_text
    assert results[0].status == "applied"
    assert results[0].detail == "applied_whitespace_tolerant"


def test_word_fallback_applies_when_unique_and_enabled():
    text = "Цхьа Аълбикин хилла."
    rows = [
        {
            "id": "1",
            "word": "Аълбикин",
            "replacement": "Аьлбикин",
            "corrected_context": "context that will not match anything [[Аълбикин]]",
            "decision": "replace",
        }
    ]

    new_text, results = apply_review_rows(text, rows, allow_word_fallback=True)

    assert new_text == "Цхьа Аьлбикин хилла."
    assert results[0].status == "applied"
    assert results[0].detail == "applied_unique_word_fallback"


def test_word_fallback_refuses_when_ambiguous():
    text = "Аълбикин ву цигахь. Аълбикин ву кхузахь а."
    rows = [
        {
            "id": "1",
            "word": "Аълбикин",
            "replacement": "Аьлбикин",
            "corrected_context": "context that will not match anything [[Аълбикин]]",
            "decision": "replace",
        }
    ]

    new_text, results = apply_review_rows(text, rows, allow_word_fallback=True)

    # Neither the context-based attempt nor the fallback could apply
    # safely (fallback found 2 ambiguous matches) -- text is untouched.
    # The reported detail reflects the first (context) attempt, matching
    # the original tool's behavior: a failed fallback doesn't overwrite
    # the initial result, only a successful one does.
    assert new_text == text
    assert results[0].status == "skipped"


def test_word_equals_replacement_is_skipped():
    text = "Цхьа Аълбикин хилла."
    rows = [
        {
            "id": "1",
            "word": "Аълбикин",
            "replacement": "Аълбикин",
            "corrected_context": "Цхьа [[Аълбикин]] хилла.",
            "decision": "replace",
        }
    ]

    new_text, results = apply_review_rows(text, rows)

    assert new_text == text
    assert results[0].detail == "word_equals_replacement"


def test_overlapping_nearby_contexts_all_apply_correctly():
    # Found via real-world usage: suspicious words close together on
    # the same page have saved context windows that overlap each
    # other (one row's context contains another row's target word).
    # Applying rows one at a time against a progressively-mutated
    # text meant an earlier row's edit silently invalidated a later
    # row's saved context. All four rows here have overlapping
    # contexts by construction; all four must still apply.
    text = "цхьа аПов а йоцуш, алартех тера, кадечу бТаьхоша хӀаллакбина."
    rows = [
        {
            "id": "1",
            "word": "аПов",
            "replacement": "гӀовгӀа",
            "corrected_context": "цхьа [[аПов]] а йоцуш, алартех тера, кадечу бТаьхоша",
            "decision": "replace",
        },
        {
            "id": "2",
            "word": "бТаьхоша",
            "replacement": "бӀаьхоша",
            "corrected_context": "цхьа аПов а йоцуш, алартех тера, кадечу [[бТаьхоша]] хӀаллакбина.",
            "decision": "replace",
        },
    ]

    new_text, results = apply_review_rows(text, rows)

    assert all(r.status == "applied" for r in results), results
    assert "гӀовгӀа" in new_text
    assert "бӀаьхоша" in new_text
    assert "аПов" not in new_text
    assert "бТаьхоша" not in new_text


def test_genuinely_overlapping_target_spans_only_apply_the_first():
    # A pathological case distinct from the above: two rows whose
    # LOCATED TARGET SPANS (not just their context windows) genuinely
    # overlap. Rather than risk corrupting the text by applying both,
    # the first row (original order) wins and the second is skipped.
    text = "хТара дела."
    rows = [
        {
            "id": "1",
            "word": "хТара",
            "replacement": "хӀара",
            "corrected_context": "[[хТара]] дела.",
            "decision": "replace",
        },
        {
            "id": "2",
            "word": "хТара",  # same target word/span as row 1
            "replacement": "нечто_другое",
            "corrected_context": "[[хТара]] дела.",
            "decision": "replace",
        },
    ]

    new_text, results = apply_review_rows(text, rows)

    assert results[0].status == "applied"
    assert results[1].status == "skipped"
    assert results[1].detail == "overlaps_another_row"
    assert "хӀара" in new_text
    assert "нечто_другое" not in new_text
