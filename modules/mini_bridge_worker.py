"""Authenticated Mini App actions enter the existing PTB application, not Telegram getUpdates."""
import asyncio
from contextvars import ContextVar
import time
from telegram import Update

active_mini_action = ContextVar('active_mini_action', default=None)


def photo_round(photos, chat_id):
    game = photos.active_photo_quizzes.get(chat_id)
    if game and game.is_active and game.start_time and game.phase == 'active':
        return f'{game.session_id}:{game.current_question_index}'
    return None


def make_update(action, snapshot, app, user_id, name):
    player = {'id': user_id, 'is_bot': False, 'first_name': name or 'Игрок'}
    room = {'id': user_id, 'type': 'private', 'first_name': name or 'Игрок'}
    mid = 1_000_000_000 + int(action['request_id'].replace('-', '')[:7], 16)
    raw = {'update_id': mid}
    kind = action['type']
    if kind in {'command', 'text'}:
        message = {'message_id': mid, 'from': player, 'chat': room, 'date': int(time.time()), 'text': action['value']}
        if kind == 'command':
            message['entities'] = [{'type': 'bot_command', 'offset': 0, 'length': len(action['value'])}]
        raw['message'] = message
    else:
        card = next(m for m in snapshot['messages'] if m['id'] == action['message_id'])
        if kind == 'callback':
            message = {'message_id': card['id'], 'from': {'id': app.bot.id, 'is_bot': True, 'first_name': app.bot.first_name}, 'chat': room,
                       'date': int(card['at']), 'text': card['text'] or 'Morning Quiz'}
            raw['callback_query'] = {'id': 'mini-' + action['request_id'], 'from': player,
                                    'chat_instance': 'mini-private', 'message': message, 'data': action['value']}
        else:
            raw['poll_answer'] = {'poll_id': card['poll']['id'], 'user': player, 'option_ids': [action['value']]}
            persistent = card.get('_option_persistent_ids')
            state = app.bot_data.get('bot_state')
            info = state.get_current_poll_data(card['poll']['id']) if state else None
            persistent = persistent or (info or {}).get('option_persistent_ids')
            if persistent and action['value'] < len(persistent):
                raw['poll_answer']['option_persistent_ids'] = [persistent[action['value']]]
    return Update.de_json(raw, app.bot)


async def run_worker(bridge, app, photos, scope, dispatch_lock):
    await bridge.heartbeat(photo_round(photos, scope.chat_id), restart=True)
    last_heartbeat = 0
    while True:
        try:
            if time.monotonic() - last_heartbeat > 3:
                await bridge.heartbeat(photo_round(photos, scope.chat_id))
                last_heartbeat = time.monotonic()
            claimed = await bridge.claim()
            if claimed:
                action, snapshot = claimed
                marker = active_mini_action.set({'id': action['request_id'], 'error': None})
                try:
                    async with dispatch_lock:
                        if action['type'] == 'command' and action['value'] in {'/quiz', '/photo_quiz'}:
                            scope.enable_local_delivery()
                        if action['type'] == 'text' and action.get('round') != photo_round(photos, scope.chat_id):
                            raise ValueError('Фото-вопрос сменился')
                        from storage.models import User
                        from storage.admin_actions import AdminActions
                        if not await AdminActions(bridge.database).allowed(scope.chat_id, scope.chat_id):
                            raise ValueError('Доступ к игре закрыт')
                        async with bridge.database.transaction() as session:
                            player = await session.get(User, scope.chat_id)
                            name = player.display_name if player else 'Игрок'
                        update = make_update(action, snapshot, app, scope.chat_id, name)
                        if not scope.accepts(update):
                            raise ValueError('Действие вне согласованной лички')
                        if update.message:
                            scope.local_message_ids.append(update.message.message_id)
                        # This is an authenticated app action, NOT a fabricated Telegram event.
                        scope.event('mini_app_action', kind=action['type'])
                        await app.process_update(update)
                        game_runtime = app.bot_data.get('game_runtime')
                        if game_runtime is not None:
                            from telegram.ext import CallbackContext
                            await game_runtime.deadline_job(CallbackContext(app))
                        await bridge.finish(action['request_id'], active_mini_action.get()['error'], active_mini_action.get().get('notice'))
                        if action['type'] == 'command' and action['value'] in {'/stopquiz', '/stop_photo_quiz'}:
                            scope.disable_local_delivery()
                        await bridge.heartbeat(photo_round(photos, scope.chat_id))
                except Exception as exc:
                    scope.event('mini_app_failed', exception=type(exc).__name__)
                    await bridge.finish(action['request_id'], 'Не удалось выполнить действие. Проверьте текущее состояние игры.')
                finally:
                    active_mini_action.reset(marker)
            # The app immediately re-reads after a tap; keep the local hand-off
            # below one UI beat without busy-looping the database.
            await asyncio.sleep(0.10)
        except asyncio.CancelledError:
            raise
        except Exception:
            scope.event('mini_bridge_unavailable')
            await asyncio.sleep(2)
