"""Validated desired schedules shared by storage, API and bot workers."""
from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
import json
import re

import pytz


@dataclass(frozen=True)
class SchedulePlan:
    kind: str
    timezone: str
    times: tuple[tuple[int, int], ...]

    @property
    def token(self):
        payload = json.dumps([self.kind, self.timezone, self.times], separators=(",", ":"))
        return sha256(payload.encode()).hexdigest()[:24]


def effective_settings(values, defaults=None, daily_defaults=None):
    result = deepcopy(defaults or {})
    result["daily_quiz"] = {**(daily_defaults or {}), **result.get("daily_quiz", {})}
    for key, value in values.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key].update(deepcopy(value))
        else:
            result[key] = deepcopy(value)
    return result


def build_schedule_plan(values, kind, *, defaults=None, daily_defaults=None):
    if kind not in {"quiz", "wisdom"}:
        raise ValueError("Unknown schedule kind")
    settings = effective_settings(values, defaults, daily_defaults)
    config = settings.get("daily_quiz" if kind == "quiz" else "daily_wisdom", {})
    if not isinstance(config, dict):
        raise ValueError("Настройки расписания должны быть объектом")
    enabled = config.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ValueError("enabled должен быть логическим значением")
    if not enabled:
        return SchedulePlan(kind, "UTC", ())
    zone = settings.get("daily_quiz", {}).get("timezone", "Europe/Moscow")
    if not isinstance(zone, str) or zone not in pytz.all_timezones_set:
        raise ValueError("Неизвестный часовой пояс")
    if kind == "quiz":
        entries = config.get("times_msk", [])
        # Legacy chats can be enabled with an empty list: historically this
        # meant no quiz jobs, and must not prevent their wisdom from running.
        if not isinstance(entries, list) or len(entries) > 24:
            raise ValueError("Укажите список не более чем из 24 времён запуска")
        times = []
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError("Время должно содержать hour и minute")
            h, m = entry.get("hour"), entry.get("minute")
            if type(h) is not int or type(m) is not int or not (0 <= h <= 23 and 0 <= m <= 59):
                raise ValueError("Некорректное время запуска")
            times.append((h, m))
        if len(times) != len(set(times)):
            raise ValueError("Времена запуска не должны повторяться")
    else:
        value = config.get("time", "09:00")
        if not isinstance(value, str) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
            raise ValueError("Время мудрости должно быть в формате ЧЧ:ММ")
        times = [tuple(map(int, value.split(":")))]
    return SchedulePlan(kind, zone, tuple(sorted(times)))


def validate_schedule_settings(values):
    # Disabled quizzes may have no times yet. Validate any supplied times and
    # zones as well, so malformed values cannot hide behind an off switch.
    quiz = values.get("daily_quiz", {})
    if isinstance(quiz, dict) and quiz.get("enabled") is True and not quiz.get("times_msk"):
        raise ValueError("Для включённого квиза укажите от 1 до 24 времён запуска")
    if isinstance(quiz, dict) and "timezone" in quiz:
        zone = quiz["timezone"]
        if not isinstance(zone, str) or zone not in pytz.all_timezones_set:
            raise ValueError("Неизвестный часовой пояс")
    for kind in ("quiz", "wisdom"):
        build_schedule_plan(values, kind)
        key = "daily_quiz" if kind == "quiz" else "daily_wisdom"
        config = values.get(key, {})
        has_time = ("times_msk" in config and config["times_msk"] != []) if kind == "quiz" else "time" in config
        if not config.get("enabled") and has_time:
            candidate = deepcopy(values)
            candidate[key]["enabled"] = True
            build_schedule_plan(candidate, kind)
