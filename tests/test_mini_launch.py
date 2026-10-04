import pytest

from modules.mini_app_launch import configured_url, launch_button


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
