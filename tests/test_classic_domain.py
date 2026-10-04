from datetime import datetime, timezone

import pytest

from domain.classic import (
    advance_classic,
    classic_deadlines,
    close_round,
    finish_classic,
    on_answer_applied,
    prepare_classic,
    project_classic,
    start_classic,
    validate_classic_answer,
)


QUESTIONS = [
    {
        "question": "Два плюс два?",
        "options": ["3", "4", "5"],
        "correct_option_text": "4",
        "solution": "Это четыре.",
        "original_category": "Наука",
    },
    {
        "question": "Столица Франции?",
        "options": ["Париж", "Рим"],
        "correct_option_text": "Париж",
        "original_category": "География",
    },
]


def prepared():
    ids = iter(("round-one", "round-two"))
    return prepare_classic(
        chat_id=-100,
        creator_id=7,
        questions=QUESTIONS,
        open_seconds=30,
        interval_seconds=5,
        round_id_factory=lambda: next(ids),
        shuffle=lambda values: None,
    )


def test_prepare_freezes_question_order_and_hides_answers():
    state = prepared()
    assert state["status"] == "prepared"
    assert state["rounds"][0]["options"] == ["3", "4", "5"]
    assert state["rounds"][0]["correct_option_index"] == 1

    state = start_classic(state, expected_revision=0, now=100)
    view = project_classic(state, now=101)
    assert view["question"]["round_id"] == "round-one"
    assert "correct_option" not in view["question"]
    assert classic_deadlines(state) == {"close:round-one": 130.0}


def test_answer_schedules_one_advance_and_revision_is_optimistic():
    state = start_classic(prepared(), expected_revision=0, now=100)
    question = validate_classic_answer(
        state, round_id="round-one", selected_option=1, now=101
    )
    assert question["correct_option_index"] == 1

    state = on_answer_applied(state, round_id="round-one", now=101)
    revision = state["revision"]
    assert classic_deadlines(state)["advance:round-one"] == 106
    assert on_answer_applied(state, round_id="round-one", now=102) == state

    with pytest.raises(RuntimeError, match="уже изменилась"):
        advance_classic(
            state, round_id="round-one", cause="answer",
            expected_revision=revision - 1, now=106,
        )
    state = advance_classic(
        state, round_id="round-one", cause="answer",
        expected_revision=revision, now=106,
    )
    assert state["current_round_id"] == "round-two"
    assert state["rounds"][0]["status"] == "open"
    assert set(classic_deadlines(state)) == {"close:round-one", "close:round-two"}


def test_old_round_can_be_answered_but_cannot_advance_new_round():
    state = start_classic(prepared(), expected_revision=0, now=100)
    state = on_answer_applied(state, round_id="round-one", now=101)
    state = advance_classic(
        state, round_id="round-one", cause="answer",
        expected_revision=state["revision"], now=106,
    )
    assert validate_classic_answer(
        state, round_id="round-one", selected_option=0, now=120
    )["round_id"] == "round-one"
    unchanged = on_answer_applied(state, round_id="round-one", now=120)
    assert unchanged == state
    with pytest.raises(ValueError, match="не является текущим"):
        advance_classic(
            state, round_id="round-one", cause="deadline",
            expected_revision=state["revision"], now=131,
        )


def test_timeout_advances_then_last_close_finishes():
    state = start_classic(prepared(), expected_revision=0, now=100)
    state = advance_classic(
        state, round_id="round-one", cause="deadline",
        expected_revision=state["revision"], now=130,
    )
    assert state["rounds"][0]["status"] == "closed"
    assert state["rounds"][1]["closes_at"] == 160
    state = close_round(state, round_id="round-two", now=160)
    assert state["status"] == "finished"
    assert state["finish_reason"] == "completed"
    assert classic_deadlines(state) == {}


def test_projection_reveals_only_own_answer_or_expired_question():
    state = start_classic(prepared(), expected_revision=0, now=100)
    hidden = project_classic(state, now=101)["question"]
    answered = project_classic(state, selected_options={"round-one": 1}, now=101)["question"]
    expired = project_classic(state, now=131)["question"]
    assert "correct_option" not in hidden
    assert answered["correct_option"] == 1 and answered["is_correct"] is True
    assert expired["correct_option"] == 1 and expired["is_correct"] is None


def test_terminal_state_rejects_new_answers_and_stop_is_idempotent():
    state = start_classic(prepared(), expected_revision=0, now=100)
    state = finish_classic(
        state, reason="stopped", expected_revision=state["revision"], now=105
    )
    assert state["status"] == "stopped"
    assert finish_classic(
        state, reason="stopped", expected_revision=state["revision"], now=106
    ) == state
    with pytest.raises(ValueError, match="не активна"):
        validate_classic_answer(
            state, round_id="round-one", selected_option=0, now=106
        )


def test_datetime_and_validation_edges():
    state = start_classic(
        prepared(), expected_revision=0,
        now=datetime.fromtimestamp(100, timezone.utc),
    )
    with pytest.raises(ValueError, match="вариант"):
        validate_classic_answer(
            state, round_id="round-one", selected_option=True, now=101
        )
    with pytest.raises(RuntimeError, match="истекло"):
        validate_classic_answer(
            state, round_id="round-one", selected_option=0, now=131
        )
