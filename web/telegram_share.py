"""Prepared messages for Telegram.WebApp.shareMessage (Bot API 8.0).

Any game can use it: the server stores a ready message for one user with
savePreparedInlineMessage, the Mini App calls shareMessage(id) and Telegram shows its own
chat picker over the app (Telegram Desktop included). The bot's inline mode is not needed.
Every failure returns None so the caller can fall back to an ordinary t.me link.
"""
import logging

import httpx

log = logging.getLogger(__name__)


class TelegramShare:
    def __init__(self, token, *, proxy=None, client=None):
        self._token = token
        if client is not None:
            self.client = client
        else:
            options = {'proxy': proxy} if proxy else {}
            self.client = httpx.AsyncClient(timeout=5, follow_redirects=False, trust_env=False, **options)

    async def close(self):
        await self.client.aclose()

    async def prepare(self, user_id, *, result_id, title, text, button_text, button_url, description=''):
        """Store an article with a URL button for user_id; return the prepared message id or None."""
        result = {'type': 'article', 'id': str(result_id)[:64], 'title': title, 'description': description,
                  'input_message_content': {'message_text': text[:4096]},
                  'reply_markup': {'inline_keyboard': [[{'text': button_text, 'url': button_url}]]}}
        payload = {'user_id': int(user_id), 'result': result, 'allow_user_chats': True,
                   'allow_group_chats': True, 'allow_channel_chats': True}
        try:
            response = await self.client.post(f'https://api.telegram.org/bot{self._token}/savePreparedInlineMessage',
                                              json=payload)
            body = response.json()
            if body.get('ok') is True and isinstance(body.get('result', {}).get('id'), str):
                return body['result']['id']
            log.warning('savePreparedInlineMessage failed: %s %s', response.status_code, body.get('description'))
        except (httpx.HTTPError, ValueError, TypeError, AttributeError) as error:
            log.warning('savePreparedInlineMessage failed: %s', type(error).__name__)
        return None
