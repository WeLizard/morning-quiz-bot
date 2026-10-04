"""Classic chat quizzes: one correct answer, durable poll identity, plain text."""
import logging
from typing import Optional

from telegram import InputPollOption, Poll
from telegram.error import BadRequest, Forbidden

from domain.classic import prepare_question
from modules.quiz_payload import prepare_options
from modules.rate_limiter import TelegramRateLimiter
from modules.telegram_transport import telegram_request

logger = logging.getLogger(__name__)


class QuizEngine:
    def __init__(self, state, app_config, data_manager):
        self.state = state
        self.app_config = app_config
        self.data_manager = data_manager
        self.rate_limiter = TelegramRateLimiter(
            max_requests_per_second=25, max_requests_per_minute_per_chat=18)

    def _prepare_poll_options(self, question_details):
        return prepare_options(question_details)

    async def send_quiz_poll(
        self, context, chat_id, question_data, poll_title_prefix,
        open_period_seconds, quiz_type, is_last_question=False,
        question_session_index=0, current_category_name=None, persist_poll=None, before_send=None,
    ) -> Optional[str]:
        try:
            prepared = prepare_question(question_data)
            delivery = prepared.delivery(prefix=poll_title_prefix, category=current_category_name)
            options = delivery['options']
            correct_index = delivery['correct_option_index']
        except (ValueError, KeyError, TypeError, AttributeError):
            logger.exception('Invalid quiz question in chat %s; not truncated or sent', chat_id)
            return None
        if not options or correct_index < 0:
            return None

        async def send():
            await self.rate_limiter.acquire(chat_id)
            if before_send is not None and not await before_send():
                raise RuntimeError('Poll cancelled: game is no longer active')
            return await context.bot.send_poll(
                chat_id=chat_id,
                question=delivery['question'],
                question_parse_mode=None,
                options=[InputPollOption(option, text_parse_mode=None) for option in options],
                type=Poll.QUIZ, correct_option_ids=[correct_index],
                open_period=open_period_seconds, is_anonymous=False,
                allows_multiple_answers=False, allows_revoting=False, shuffle_options=False,
            )

        try:
            sent = await telegram_request(send)
        except Exception as exc:
            logger.exception('Quiz send failed for chat %s; no blind resend', chat_id)
            unavailable = isinstance(exc, Forbidden) or (
                isinstance(exc, BadRequest) and 'chat not found' in str(exc).lower())
            if unavailable and quiz_type == 'daily':
                await self.data_manager.disable_daily_quiz_for_chat(
                    chat_id, reason='blocked' if isinstance(exc, Forbidden) else 'not_found')
            return None
        if not sent or not sent.poll:
            logger.error('No poll acknowledgement for chat %s; delivery unknown', chat_id)
            return None

        poll_id = sent.poll.id
        if self.state.get_current_poll_data(poll_id):
            return poll_id
        persistent_ids = [option.persistent_id for option in sent.poll.options]
        entry = {
            'chat_id': chat_id, 'message_id': sent.message_id,
            'question_details': question_data, 'correct_option_index': correct_index,
            **prepared.checkpoint(prefix=poll_title_prefix, category=current_category_name),
            'option_count': len(options),
            'option_persistent_ids': persistent_ids,
            'quiz_type': quiz_type, 'is_last_question_in_series': is_last_question,
            'question_session_index': question_session_index,
            'solution_placeholder_message_id': None, 'processed_by_early_answer': False,
            'open_timestamp': sent.date.timestamp(),
            'next_q_triggered_by_answer': False, 'job_poll_end_name': None,
        }
        self.state.add_current_poll(poll_id, entry)
        if persist_poll is not None:
            await persist_poll(poll_id)
        logger.info('Sent quiz %s to chat %s (message %s)', poll_id, chat_id, sent.message_id)
        # Publish explanations after the deadline, not as an in-poll spoiler.
        # Old checkpoints with a light-bulb placeholder remain editable below.
        return poll_id

    async def send_solution_if_available(self, context, chat_id, poll_id, *, persist_solution=None, before_send=None):
        poll = self.state.get_current_poll_data(poll_id)
        if not poll:
            return None
        if poll.get('solution_sent'):
            return poll.get('solution_message_id')
        if poll.get('solution_delivery') in ('sending', 'unknown', 'failed'):
            return None  # A crash/timeout must not replay an unacknowledged send.
        details = poll.get('question_details', {})
        solution = details.get('solution') or details.get('explanation')
        if not solution:
            return None
        text = '💡 ' + str(solution).strip()
        # Keep the one-message cleanup contract for oversized legacy solutions.
        # Make shortening explicit without altering source data.
        if len(text) > 4096:
            suffix = '\n… (пояснение сокращено)'
            text = text[:4096 - len(suffix)] + suffix

        poll['solution_delivery'] = 'sending'
        if persist_solution is not None:
            await persist_solution()  # Commit intent BEFORE the Telegram request.
        placeholder = poll.get('solution_placeholder_message_id')
        async def send_solution():
            return await telegram_request(lambda: context.bot.send_message(
                chat_id=chat_id, text=text, parse_mode=None), before_call=before_send)
        try:
            if placeholder:
                try:
                    await telegram_request(lambda: context.bot.edit_message_text(
                        chat_id=chat_id, message_id=placeholder, text=text, parse_mode=None),
                        idempotent=True, before_call=before_send)
                    message_id = placeholder
                except BadRequest as exc:
                    if 'message is not modified' in str(exc).lower():
                        message_id = placeholder
                    elif 'message to edit not found' in str(exc).lower():
                        message_id = (await send_solution()).message_id
                    else:
                        raise
            else:
                message_id = (await send_solution()).message_id
        except Exception:
            poll['solution_delivery'] = 'unknown'
            logger.exception('Solution %s not acknowledged; automatic resend suppressed', poll_id)
            if persist_solution is not None:
                await persist_solution()
            return None
        poll.update(solution_sent=True, solution_message_id=message_id, solution_delivery='sent')
        if persist_solution is not None:
            await persist_solution()
        return message_id
