import asyncio
import json

import httpx
import pytest

from modules.admin_ai import AIUnavailable, configuration, reply


@pytest.mark.parametrize('provider', ['anthropic', 'openrouter', 'puter'])
def test_provider_payload_is_bounded_and_secret_not_in_response(provider, monkeypatch):
    monkeypatch.setenv('MQB_ADMIN_AI_ENABLED', '1')
    monkeypatch.setenv(f'MQB_ADMIN_AI_{provider.upper()}_KEY', 'synthetic-secret')
    calls = []
    def handler(request):
        calls.append(request)
        value = json.loads(request.content)
        assert value['max_tokens'] == 1200 and value['stream'] is False and 'tools' not in value
        return httpx.Response(200, json={'content': [{'type': 'text', 'text': '<script>text</script>'}]} if provider == 'anthropic' else {'choices': [{'message': {'content': '<script>text</script>'}}]})
    result = asyncio.run(reply(provider, [{'role': 'user', 'content': 'Hi'}], 'configured-model',
        confirmed_external=True, transport=httpx.MockTransport(handler)))
    assert result['text'] == '<script>text</script>' and not result['simulated']
    assert len(calls) == 1
    assert 'synthetic-secret' not in json.dumps(configuration()) + json.dumps(result)
    assert calls[0].url.host in {'api.anthropic.com', 'openrouter.ai', 'api.puter.com'}


def test_ai_default_offline_never_connects_and_does_not_claim_model_output(monkeypatch):
    monkeypatch.delenv('MQB_ADMIN_AI_ENABLED', raising=False)
    def handler(_):
        pytest.fail('No external call expected')
    messages = [{'role': 'user', 'content': 'Hi'}]
    result = asyncio.run(reply('offline', messages, transport=httpx.MockTransport(handler)))
    assert result['simulated'] and 'не результат модели' in result['text']
    with pytest.raises(AIUnavailable, match='выключен'):
        asyncio.run(reply('puter', messages, transport=httpx.MockTransport(handler)))


@pytest.mark.parametrize('status', [401, 429, 500])
def test_ai_errors_are_sanitized_without_automatic_retry(status, monkeypatch):
    monkeypatch.setenv('MQB_ADMIN_AI_ENABLED', '1')
    monkeypatch.setenv('MQB_ADMIN_AI_OPENROUTER_KEY', 'synthetic-secret')
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(status, text='synthetic-secret-private-diagnostic')
    with pytest.raises(AIUnavailable) as result:
        asyncio.run(reply('openrouter', [{'role': 'user', 'content': 'Hi'}], 'model',
                          confirmed_external=True, transport=httpx.MockTransport(handler)))
    assert 'synthetic-secret' not in str(result.value) and len(calls) == 1
