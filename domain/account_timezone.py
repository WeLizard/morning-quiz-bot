"""Account-level IANA timezone preferences."""
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones


@lru_cache(maxsize=1)
def timezones() -> frozenset[str]:
    """Return the server's available IANA zones, including the stable UTC name."""
    return frozenset(available_timezones())


def parse_timezone(value: str | None) -> str | None:
    """Validate a stored preference; ``None`` means the player has not chosen one."""
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 64 or value not in timezones():
        raise ValueError('timezone')
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError('timezone') from None
    return value
