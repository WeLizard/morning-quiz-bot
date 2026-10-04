"""Telegram Mini App HMAC validation. No initDataUnsafe, cookies or admin keys."""
from dataclasses import dataclass
from hashlib import sha256
import hmac
import json
import re
from urllib.parse import parse_qsl


class InvalidInitData(ValueError):
    pass


@dataclass(frozen=True)
class TelegramIdentity:
    user_id: int
    auth_date: int
    fingerprint: str


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key')
        result[key] = value
    return result


def validate_init_data(raw, bot_token, *, now, max_age=300, future_skew=30):
    """HMAC includes all decoded fields except hash (including signature, if present)."""
    try:
        if not isinstance(raw, str) or not 1 <= len(raw.encode('utf-8')) <= 16384:
            raise ValueError()
        if re.search(r'%(?![0-9a-fA-F]{2})', raw):
            raise ValueError()
        pairs = parse_qsl(raw, keep_blank_values=True, strict_parsing=True,
                          encoding='utf-8', errors='strict', max_num_fields=32)
        fields = unique_object(pairs)
        if any(not re.fullmatch(r'[a-z_]+', key) or '\n' in value or '\r' in value
               for key, value in fields.items()):
            raise ValueError()
        received = fields.pop('hash')
        if not re.fullmatch('[0-9a-fA-F]{64}', received):
            raise ValueError()
        check = '\n'.join(f'{key}={fields[key]}' for key in sorted(fields))
        secret = hmac.digest(b'WebAppData', bot_token.encode(), 'sha256')
        expected = hmac.new(secret, check.encode(), sha256).hexdigest()
        if not hmac.compare_digest(expected, received.lower()):
            raise ValueError()
        date = fields['auth_date']
        if not re.fullmatch(r'[0-9]{1,12}', date):
            raise ValueError()
        timestamp = int(date)
        if not now - max_age <= timestamp <= now + future_skew:
            raise ValueError()
        user = json.loads(fields['user'], object_pairs_hook=unique_object)
        uid = user['id']
        if type(uid) is not int or not 0 < uid < 2**52 or user.get('is_bot', False) is not False:
            raise ValueError()
        return TelegramIdentity(uid, timestamp, expected)
    except (ValueError, KeyError, TypeError, UnicodeError, AttributeError, RecursionError):
        raise InvalidInitData('Недействительные или просроченные данные Telegram') from None
