import pytest

from modules.mini_app_launch import configured_url, deep_link, direct_mafia_link, launch_button


def test_deep_links_cover_pages_and_group_chats(monkeypatch):
    monkeypatch.setenv('MINI_APP_URL', 'https://quiz.example.com/app')
    for page in ('home', 'chats', 'rating', 'profile', 'achievements', 'history'):
        assert deep_link('quizbot', page) == f'https://t.me/quizbot?startapp={page}'
    assert deep_link('quizbot', 'chat', -1002123346533) == 'https://t.me/quizbot?startapp=chat_n1002123346533'
    assert direct_mafia_link('quizbot', -1002123346533) == 'https://t.me/quizbot?startapp=mafia_n1002123346533'


@pytest.mark.parametrize('target,chat_id', [('unknown-page', None), ('chat', None), ('chat', 42),
    ('mafia', 0), ('chat', True), ('chat', -1002123346533.0)])
def test_deep_links_reject_unknown_pages_and_bad_group_ids(monkeypatch, target, chat_id):
    monkeypatch.setenv('MINI_APP_URL', 'https://quiz.example.com/app')
    with pytest.raises(ValueError):
        deep_link('quizbot', target, chat_id)


def test_deep_links_require_configured_url_and_valid_bot_username(monkeypatch):
    monkeypatch.delenv('MINI_APP_URL', raising=False)
    assert deep_link('quizbot', 'home') is None and direct_mafia_link('quizbot', -1001234567890) is None
    monkeypatch.setenv('MINI_APP_URL', 'https://quiz.example.com/app')
    with pytest.raises(ValueError):
        deep_link('bad username', 'home')


def test_mini_launch_opt_in_and_private_only(monkeypatch):
    monkeypatch.delenv('MINI_APP_URL', raising=False)
    assert configured_url() is None and launch_button('private') is None
    monkeypatch.setenv('MINI_APP_URL', 'https://quiz.example.com/app')
    assert launch_button('private').web_app.url == 'https://quiz.example.com/app'
    assert launch_button('supergroup') is None


@pytest.mark.parametrize('url', ['http://quiz.example.com/app', 'https://127.0.0.1/app', 'https://localhost/app',
    'https://192.168.0.33/app', 'https://user:secret@quiz.example.com/app', 'https://quiz.example.com/app?token=bad'])
def test_mini_launch_rejects_local_admin_and_credentials(monkeypatch, url):
    monkeypatch.setenv('MINI_APP_URL', url)
    with pytest.raises(ValueError):
        configured_url()
