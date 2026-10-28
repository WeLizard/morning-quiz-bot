import asyncio
import time

import pytest

from application import photo_selection
from domain.photo import prepare_photo


class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class _Session:
    def __init__(self, rows):
        self.rows = rows

    async def execute(self, _statement):
        return _Rows(self.rows)


def _rows(count):
    return [(f'photo-{index:04}', f'answer {index}', True,
             {'storage_name': f'photo-{index:04}', 'image_sha256': 'a' * 64})
            for index in range(count)]


def test_setup_large_catalog_is_metadata_only(monkeypatch):
    def forbidden(*_args):
        raise AssertionError('setup must not touch image files')

    monkeypatch.setattr(photo_selection, 'verified_image_path', forbidden)
    available = asyncio.run(photo_selection.available_photo_questions(_Session(_rows(1605))))
    assert len(available) == 1605


def test_setup_excludes_legacy_content_digest_answers():
    rows = _rows(2)
    digest_answer = 'sha256-' + 'a' * 64
    rows.append(('legacy-hash-answer', digest_answer, True,
                 {'display_answer': digest_answer, 'storage_name': 'legacy-hash-answer'}))

    available = asyncio.run(photo_selection.available_photo_questions(_Session(rows)))

    assert [item['media']['media_key'] for item in available] == ['photo-0000', 'photo-0001']


def test_photo_round_uses_curated_candidate_instead_of_legacy_digest_answer(monkeypatch):
    digest_answer = 'sha256-' + 'b' * 64
    rows = [
        ('legacy-hash-answer', digest_answer, True,
         {'display_answer': digest_answer, 'storage_name': 'owl', 'image_sha256': 'a' * 64}),
        ('owl', 'Сова', True,
         {'display_answer': 'Сова', 'storage_name': 'owl', 'image_sha256': 'a' * 64}),
    ]
    monkeypatch.setattr(photo_selection, 'images_root', lambda: 'unused')
    monkeypatch.setattr(photo_selection.random.SystemRandom, 'shuffle', lambda _self, items: None)
    monkeypatch.setattr(photo_selection, 'verified_image_path', lambda _root, key, _metadata: key)

    selected = asyncio.run(photo_selection.select_photo_questions(_Session(rows), 1))
    state = prepare_photo(chat_id=1, creator_id=2, questions=selected, now=100)

    round_item = state['rounds'][0]
    assert round_item['display_answer'] == 'Сова'
    assert len(round_item['masks']['initial']) == len('Сова')
    assert 'sha256-' not in str(round_item)


def test_start_verifies_only_until_requested_count_and_skips_corrupt_candidates(monkeypatch):
    rows = _rows(100)
    # Put a missing/corrupt candidate first to prove selection continues to a valid one.
    rows[0] = ('photo-0000', 'answer 0', True,
               {'storage_name': 'missing', 'image_sha256': 'a' * 64})
    monkeypatch.setattr(photo_selection.random.SystemRandom, 'shuffle', lambda _self, items: None)
    checked = []

    def recording_verify(_root, key, _metadata):
        checked.append(key)
        # Candidate 0 represents a missing/corrupt file; the remainder are valid.
        return None if key == 'photo-0000' else key

    monkeypatch.setattr(photo_selection, 'verified_image_path', recording_verify)
    selected = asyncio.run(photo_selection.select_photo_questions(_Session(rows), 3))
    assert len(selected) == 3
    assert all(item['media']['media_key'] != 'photo-0000' for item in selected)
    assert len(checked) == 16


def test_all_invalid_candidates_raise_without_mutating_session(monkeypatch):
    rows = _rows(5)
    session = _Session(rows)
    monkeypatch.setattr(photo_selection.random.SystemRandom, 'shuffle', lambda _self, items: None)
    monkeypatch.setattr(photo_selection, 'verified_image_path', lambda *_args: None)

    with pytest.raises(LookupError, match='В каталоге нет доступных фото-загадок'):
        asyncio.run(photo_selection.select_photo_questions(session, 3))
    assert session.rows == rows


def test_fewer_valid_candidates_repeat_cyclically(monkeypatch):
    rows = _rows(3)
    monkeypatch.setattr(photo_selection.random.SystemRandom, 'shuffle', lambda _self, items: None)
    monkeypatch.setattr(photo_selection, 'verified_image_path',
                        lambda _root, key, _metadata: key if key == 'photo-0001' else None)

    selected = asyncio.run(photo_selection.select_photo_questions(_Session(rows), 4))
    assert [item['media']['media_key'] for item in selected] == ['photo-0001'] * 4


def test_valid_candidate_after_fully_invalid_first_batch_is_found(monkeypatch):
    rows = _rows(20)
    monkeypatch.setattr(photo_selection.random.SystemRandom, 'shuffle', lambda _self, items: None)
    checked = []

    def verify(_root, key, _metadata):
        checked.append(key)
        return key if key == 'photo-0017' else None

    monkeypatch.setattr(photo_selection, 'verified_image_path', verify)
    selected = asyncio.run(photo_selection.select_photo_questions(_Session(rows), 1))
    assert [item['media']['media_key'] for item in selected] == ['photo-0017']
    assert len(checked) == 20


def test_slow_file_verification_does_not_block_event_loop(monkeypatch):
    async def run():
        session = _Session(_rows(16))
        monkeypatch.setattr(photo_selection, 'images_root', lambda: 'unused')
        monkeypatch.setattr(photo_selection.random.SystemRandom, 'shuffle', lambda _self, items: None)
        def slow_verify(_root, key, _metadata):
            time.sleep(0.1)
            return key
        monkeypatch.setattr(photo_selection, 'verified_image_path', slow_verify)
        selection = asyncio.create_task(photo_selection.select_photo_questions(session, 3))
        await asyncio.sleep(0.01)
        responsive = not selection.done()
        await selection
        assert responsive

    asyncio.run(run())
