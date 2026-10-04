"""Bounded text-only provider adapters. No tools, code execution or implicit data access."""
import os
import json

import httpx

PROVIDERS = {
    'anthropic': ('Anthropic', 'https://api.anthropic.com/v1/messages'),
    'openrouter': ('OpenRouter', 'https://openrouter.ai/api/v1/chat/completions'),
    'puter': ('Puter', 'https://api.puter.com/puterai/openai/v1/chat/completions'),
}


class AIUnavailable(ValueError):
    pass


def configuration():
    enabled = os.getenv('MQB_ADMIN_AI_ENABLED') == '1'
    return {'external_enabled': enabled, 'providers': [
        {'id': key, 'name': name, 'key_configured': bool(os.getenv(f'MQB_ADMIN_AI_{key.upper()}_KEY')),
         'default_model': os.getenv(f'MQB_ADMIN_AI_{key.upper()}_MODEL', '')}
        for key, (name, _) in PROVIDERS.items()]}


async def reply(provider, messages, model='', *, confirmed_external=False, transport=None):
    if not 1 <= len(messages) <= 40 or messages[-1]['role'] != 'user':
        raise ValueError('Нужна история до 40 сообщений, заканчивающаяся запросом пользователя')
    if sum(len(m['content']) for m in messages) > 24000:
        raise ValueError('История слишком длинная. Начните новый разговор.')
    if provider == 'offline':
        return {'provider': 'offline', 'model': None, 'simulated': True,
                'text': 'Демонстрационный ответ — не результат модели.\n\n'
                        'Запрос принят; история диалога и отображение текста работают. '
                        'Для настоящего AI выберите настроенного провайдера. Данные бота автоматически не передаются.'}
    if provider not in PROVIDERS:
        raise ValueError('Неизвестный провайдер')
    if os.getenv('MQB_ADMIN_AI_ENABLED') != '1' or not confirmed_external:
        raise AIUnavailable('Внешний AI выключен. Нужны серверная настройка и подтверждение передачи текста.')
    prefix = f'MQB_ADMIN_AI_{provider.upper()}'
    key = os.getenv(prefix + '_KEY', '')
    model = model or os.getenv(prefix + '_MODEL', '')
    if not key or not model:
        raise AIUnavailable('Для провайдера не заданы отдельный ключ или ID модели.')
    payload = {'model': model, 'messages': messages, 'max_tokens': 1200, 'stream': False}
    headers = {'x-api-key': key, 'anthropic-version': '2023-06-01'} if provider == 'anthropic' else {'Authorization': 'Bearer ' + key}
    try:
        async with httpx.AsyncClient(timeout=45, follow_redirects=False, trust_env=False, transport=transport) as client:
            async with client.stream('POST', PROVIDERS[provider][1], json=payload, headers=headers) as response:
                if response.status_code in {401, 403}:
                    raise AIUnavailable('Провайдер отклонил авторизацию. Проверьте отдельный ключ на сервере.')
                if response.status_code == 429:
                    raise AIUnavailable('Лимит провайдера. Автоматического повтора нет; попробуйте позже.')
                if not 200 <= response.status_code < 300:
                    raise AIUnavailable('Провайдер не выполнил запрос. Проверьте ID модели и настройки аккаунта.')
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > 1_000_000:
                        raise AIUnavailable('Ответ провайдера превышает лимит.')
                data = json.loads(body)
        if provider == 'anthropic':
            text = '\n'.join(block['text'] for block in data['content'] if block['type'] == 'text')
        else:
            text = data['choices'][0]['message']['content']
        if not isinstance(text, str) or not text.strip() or len(text) > 24000:
            raise AIUnavailable('Провайдер вернул пустой или неподдерживаемый ответ.')
        return {'provider': provider, 'model': model, 'simulated': False, 'text': text}
    except httpx.TimeoutException:
        raise AIUnavailable('Время ожидания истекло. Запрос мог быть обработан; автоматического повтора нет.') from None
    except httpx.HTTPError:
        raise AIUnavailable('Нет связи с провайдером. Ключ и ответ сервера не раскрываются.') from None
    except (KeyError, IndexError, TypeError, json.JSONDecodeError):
        raise AIUnavailable('Неожиданный формат ответа провайдера.') from None
