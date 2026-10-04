"""Compatibility helpers for the shared classic-quiz domain contract."""

import random

from domain.classic import prepare_question, question_with_header


def prepare_options(question):
    prepared = prepare_question(question, shuffle=random.shuffle)
    return (
        prepared.text,
        list(prepared.options),
        prepared.correct_option_index,
        prepared.correct_option_text,
    )


def selected_option_index(answer, poll):
    """Reject malformed/mismatched votes, retaining compatibility with old checkpoints."""
    indices = answer.option_ids
    if len(indices) != 1 or type(indices[0]) is not int or indices[0] < 0:
        return None
    index = indices[0]
    count = poll.get('option_count')
    if count is not None and index >= count:
        return None
    stored_ids = poll.get('option_persistent_ids')
    if stored_ids:
        received_ids = getattr(answer, 'option_persistent_ids', ())
        if len(received_ids) != 1 or index >= len(stored_ids) or stored_ids[index] != received_ids[0]:
            return None
    return index
