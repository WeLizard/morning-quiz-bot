"""The move announcement: right text and button per chat kind, groups first, no stray recipients."""
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    'handover_announce', Path(__file__).resolve().parents[1] / 'scripts' / 'handover_announce.py')
announce = importlib.util.module_from_spec(spec)
spec.loader.exec_module(announce)


def test_groups_are_asked_to_add_the_bot_and_private_chats_to_open_it():
    group = announce.message(-100123, '1 декабря')
    private = announce.message(123, '1 декабря')
    assert 'добавьте @Quizywizzy_bot в этот чат' in group['text'] and '1 декабря' in group['text']
    assert group['reply_markup']['inline_keyboard'][0][0]['url'] == 'https://t.me/Quizywizzy_bot?startgroup=1'
    assert 'нажмите «Старт»' in private['text'] and '1 декабря' in private['text']
    assert private['reply_markup']['inline_keyboard'][0][0]['url'].startswith('https://t.me/Quizywizzy_bot?start=')
    assert all(len(body['text']) < 4096 for body in (group, private))


def test_recipients_come_from_the_chat_folders_groups_first(tmp_path):
    for name in ('5', '-100200', '-4', '17', 'not-a-chat'):
        (tmp_path / name).mkdir()
    (tmp_path / '99').write_text('a file, not a chat')
    assert announce.recipients(tmp_path) == [-100200, -4, 5, 17]
    assert announce.recipients(tmp_path, ['17', '-4']) == [-4, 17]
    with pytest.raises(SystemExit):
        announce.recipients(tmp_path, ['42'])
