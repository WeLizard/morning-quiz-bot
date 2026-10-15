"""Invitation destinations: Telegram direct Mini App, standalone and draft."""
from urllib.parse import parse_qs, urlsplit

import pytest

from qw_farm.sharing import invite_info

ID = 'aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee'


def test_telegram_invitation_share_and_personal_draft_open_registered_app():
    info = invite_info(ID, 'Ира', origin='https://qw.example',
                       bot_username='Quizywizzy_bot', recipient='FriendlyUser')
    link = f'https://t.me/Quizywizzy_bot/play?startapp=farm_{ID}'
    assert info['mini_app_url'] == link
    assert parse_qs(urlsplit(info['share_url']).query)['url'] == [link]
    assert link in info['text']
    assert link in parse_qs(urlsplit(info['direct_url']).query)['text'][0]
    assert info['web_url'] == f'https://qw.example/app/farm?invite={ID}'


def test_custom_short_name_and_standalone_fallback():
    assert '/other_app?' in invite_info(ID, 'Ира', bot_username='QuizzyBot',
                                      mini_app_short_name='other_app')['mini_app_url']
    info = invite_info(ID, 'Ира', origin='https://qw.example')
    assert info['mini_app_url'] is None
    assert info['web_url'] in info['text']
    assert parse_qs(urlsplit(info['share_url']).query)['url'] == [info['web_url']]


@pytest.mark.parametrize('name', ['../play', 'play?bad=1', 'https://evil.test', 'ab', 'x' * 31])
def test_invalid_short_name_is_rejected(name):
    with pytest.raises(Exception) as error:
        invite_info(ID, 'Ира', bot_username='QuizzyBot', mini_app_short_name=name)
    assert error.value.code == 'bot_configuration'
