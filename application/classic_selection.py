"""PostgreSQL-backed question selection shared by every Classic adapter."""

from copy import deepcopy
import random
import time

from sqlalchemy import select

from modules.quiz_preferences import category_preferences
from storage.models import Chat, QuestionCategory, SystemState
from storage.question_bank import QuestionBank, normalized


def _pick_categories(
    candidates, *, count, statistics, chat_id, now, shuffle,
):
    candidates = list(dict.fromkeys(candidates))
    if not candidates or count <= 0:
        return []
    if len(candidates) <= count:
        return candidates
    weighted = []
    for name in candidates:
        value = statistics.get(name)
        if not isinstance(value, dict):
            weighted.append((name, 100.0))
            continue
        last_used = value.get('last_used')
        days = max(0.0, (now - float(last_used)) / 86400) if type(last_used) in {int, float} else float('inf')
        if days < 2:
            continue
        usage = value.get('chat_usage')
        chat_usage = usage.get(str(chat_id), 0) if isinstance(usage, dict) else 0
        weight = (100.0 if not chat_usage else 100.0 / max(1, chat_usage)) + days * 2
        weighted.append((name, weight))
    weighted.sort(key=lambda item: item[1], reverse=True)
    top = weighted[:min(count * 2, len(weighted))]
    shuffle(top)
    chosen = [name for name, _ in top[:count]]
    if len(chosen) < count:
        remaining = [name for name in candidates if name not in chosen]
        shuffle(remaining)
        chosen.extend(remaining[:count - len(chosen)])
    return chosen


async def select_classic_questions(
    session,
    *,
    chat_id: int,
    count: int,
    defaults: dict | None = None,
    category_names: list[str] | None = None,
    random_categories: bool = True,
    now: float | None = None,
    shuffle=None,
):
    """Select immutable source snapshots without updating usage counters.

    Usage is committed only when the game completes, preserving the existing
    category fairness contract and avoiding a start/selection race.
    """
    if type(count) is not int or not 1 <= count <= 1000:
        raise ValueError('Количество вопросов должно быть от 1 до 1000.')
    randomize = shuffle or random.SystemRandom().shuffle
    chat = await session.get(Chat, chat_id)
    settings = deepcopy(defaults or {})
    settings.update(deepcopy(chat.settings or {}) if chat else {})
    rows = (await session.scalars(select(QuestionCategory).where(
        QuestionCategory.archived.is_(False)
    ).order_by(QuestionCategory.name))).all()
    bank = {}
    for row in rows:
        values = []
        for source in row.questions or []:
            if not QuestionBank.is_valid(source):
                continue
            clean = normalized(source)
            values.append({
                **deepcopy(source), **clean,
                'correct_option_text': clean['correct'],
                'original_category': row.name,
            })
        if values:
            bank[row.name] = values
    disabled = set(settings.get('disabled_categories') or [])
    enabled = settings.get('enabled_categories')
    if category_names and not random_categories:
        candidates = [name for name in category_names if name in bank and name not in disabled]
    else:
        mode, pool, category_count = category_preferences(settings)
        candidates = [name for name in bank if name not in disabled]
        if mode == 'specific':
            candidates = [name for name in candidates if name in pool]
        elif mode == 'exclude':
            candidates = [name for name in candidates if name not in pool]
        if enabled:
            candidates = [name for name in candidates if name in enabled]
        stats_row = await session.get(SystemState, 'category_usage_stats')
        candidates = _pick_categories(
            candidates,
            count=max(1, min(int(category_count or 3), len(candidates))),
            statistics=stats_row.payload if stats_row and isinstance(stats_row.payload, dict) else {},
            chat_id=chat_id,
            now=now if type(now) in {int, float} else time.time(),
            shuffle=randomize,
        )
    questions = [
        {**question, 'current_category_name_for_quiz': name}
        for name in candidates for question in bank[name]
    ]
    randomize(questions)
    return questions[:count]
