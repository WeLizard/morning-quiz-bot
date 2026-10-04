"""Bounded retries: explicit rejection is different from unknown delivery."""
import asyncio
from datetime import timedelta

from telegram.error import BadRequest, NetworkError, RetryAfter


async def telegram_request(call, *, before_call=None, idempotent=False, max_retries=2, retry_budget=30.0,
                           base_delay=0.1, max_delay=0.5, exponential_base=1.5):
    remaining = retry_budget
    for attempt in range(max_retries + 1):
        try:
            if before_call is not None and not await before_call():
                raise RuntimeError('Telegram operation cancelled: game is no longer active')
            return await call()
        except RetryAfter as exc:
            delay = exc.retry_after
            delay = delay.total_seconds() if isinstance(delay, timedelta) else float(delay)
            delay = max(0.0, delay)
            if attempt == max_retries or delay > remaining:
                raise
        except BadRequest:
            raise  # BadRequest is a NetworkError subclass, but retry cannot fix it.
        except NetworkError:
            if not idempotent or attempt == max_retries:
                raise  # send* may have succeeded: never create a second message blindly.
            delay = min(base_delay * exponential_base ** attempt, max_delay)
            if delay > remaining:
                raise
        remaining -= delay
        await asyncio.sleep(delay)
