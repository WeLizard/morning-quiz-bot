"""Pure scoring rules shared by Telegram and HTTP adapters."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Mapping


@dataclass(frozen=True)
class ClassicScoringRules:
    streak_enabled: bool = False
    min_streak_for_bonus: int = 3
    base_multiplier: Decimal = Decimal("0.1")
    max_multiplier: Decimal = Decimal("1")
    milestones: tuple[int, ...] = ()
    streak_milestones: tuple[int, ...] = ()

    @classmethod
    def from_settings(
        cls,
        global_settings: Mapping[str, Any] | None,
        *,
        streak_milestones: tuple[int, ...] = (),
    ) -> "ClassicScoringRules":
        settings = global_settings or {}
        bonus = settings.get("streak_bonuses") or {}
        milestone_values = []
        for value in (settings.get("chat_achievements") or {}):
            try:
                milestone_values.append(int(value))
            except (TypeError, ValueError):
                continue
        return cls(
            streak_enabled=bool(bonus.get("enabled", False)),
            min_streak_for_bonus=max(1, int(bonus.get("min_streak_for_bonus", 3))),
            base_multiplier=Decimal(str(bonus.get("base_multiplier", 0.1))),
            max_multiplier=Decimal(str(bonus.get("max_multiplier", 1))),
            milestones=tuple(sorted(set(milestone_values), key=abs, reverse=True)),
            streak_milestones=tuple(sorted(set(streak_milestones), reverse=True)),
        )


@dataclass(frozen=True)
class ScoreTransition:
    applied: bool
    points: Decimal
    milestone: int | None = None
    streak_milestone: int | None = None
    score_before: Decimal = Decimal("0")


def _as_set(value: Any) -> set[str]:
    if isinstance(value, set):
        return value
    if isinstance(value, (list, tuple)):
        return {str(item) for item in value}
    return set()


def _matching_milestone(score: Decimal, milestones: tuple[int, ...]) -> int | None:
    for threshold in milestones:
        if (threshold > 0 and score >= threshold) or (threshold < 0 and score <= threshold) or (
            threshold == 0 and score == 0
        ):
            return threshold
    return None


def apply_classic_score(
    data: dict[str, Any],
    *,
    chat_id: int,
    user_id: int,
    display_name: str,
    answer_id: str,
    is_correct: bool,
    rules: ClassicScoringRules,
    now: datetime | None = None,
) -> ScoreTransition:
    """Mutate a detached member view; callers commit it transactionally."""

    now = now or datetime.now(timezone.utc)
    today = now.date().isoformat()
    answered = _as_set(data.get("answered_polls"))
    daily = _as_set(data.get("daily_answered_polls"))
    if data.get("last_daily_reset") != today:
        daily = set()
        data["last_daily_reset"] = today
    if answer_id in answered or answer_id in daily:
        return ScoreTransition(False, Decimal("0"))

    data["name"] = display_name
    data["answered_polls"] = answered
    data["daily_answered_polls"] = daily
    data["milestones_achieved"] = _as_set(data.get("milestones_achieved"))
    data["streak_achievements_earned"] = _as_set(data.get("streak_achievements_earned"))
    old_score = Decimal(str(data.get("score", 0)))
    streak = int(data.get("consecutive_correct") or 0)
    best = int(data.get("max_consecutive_correct") or 0)

    milestone = _matching_milestone(old_score, rules.milestones)
    milestone_code = (
        f"chat_achievement_{chat_id}_{user_id}_{milestone}" if milestone is not None else None
    )
    if milestone_code in data["milestones_achieved"]:
        milestone = None
    elif milestone_code:
        data["milestones_achieved"].add(milestone_code)

    if is_correct:
        streak += 1
        multiplier = Decimal("0")
        if rules.streak_enabled and streak >= rules.min_streak_for_bonus:
            multiplier = min(Decimal(streak) * rules.base_multiplier, rules.max_multiplier)
        points = Decimal("1") + multiplier
        data["correct_answers_count"] = int(data.get("correct_answers_count") or 0) + 1
    else:
        streak = 0
        points = Decimal("-0.5")
    data["consecutive_correct"] = streak
    data["max_consecutive_correct"] = max(best, streak)
    data["score"] = float(old_score + points)
    answered.add(answer_id)
    daily.add(answer_id)
    stamp = now.astimezone(timezone.utc).isoformat()
    data["first_answer_time"] = data.get("first_answer_time") or stamp
    data["last_answer_time"] = stamp

    streak_milestone = None
    if is_correct:
        streak_milestone = next(
            (threshold for threshold in rules.streak_milestones if streak >= threshold), None
        )
        # Streak messages are ephemeral celebrations, not persistent grants.
    return ScoreTransition(True, points, milestone, streak_milestone, old_score)
