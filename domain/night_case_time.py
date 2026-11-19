"""Pure UTC and civil-time calculations for the night case core rules."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

UTC = timezone.utc


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("expected aware UTC datetime")
    return value.astimezone(UTC)


def _parse(value: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("expected canonical UTC timestamp")
    result = datetime.fromisoformat(value[:-1] + "+00:00")
    if result.isoformat(timespec="microseconds").replace("+00:00", "Z") != value and result.isoformat().replace("+00:00", "Z") != value:
        raise ValueError("noncanonical UTC timestamp")
    return result


def _stamp(value: datetime) -> str:
    return _utc(value).isoformat().replace("+00:00", "Z")


def _civil_slot(day: date, hhmm: str, tz: ZoneInfo) -> datetime:
    hour, minute = map(int, hhmm.split(":"))
    naive = datetime.combine(day, time(hour, minute))
    valid = []
    for fold in (0, 1):
        local = naive.replace(tzinfo=tz, fold=fold)
        candidate = local.astimezone(UTC)
        if candidate.astimezone(tz).replace(tzinfo=None) == naive:
            valid.append(candidate)
    if valid:
        return max(valid)
    # A gap is short (civil DST transitions); locate its first valid minute.
    probe = naive
    for _ in range(24 * 60 + 1):
        probe += timedelta(minutes=1)
        for fold in (0, 1):
            local = probe.replace(tzinfo=tz, fold=fold)
            candidate = local.astimezone(UTC)
            if candidate.astimezone(tz).replace(tzinfo=None) == probe:
                return candidate
    raise ValueError("no valid local instant after gap")


def next_slot(after_utc: datetime, tz: str, rules) -> datetime:
    after = _utc(after_utc)
    if tz != rules.timezone:
        raise ValueError("timezone mismatch")
    zone = ZoneInfo(tz)
    day = after.astimezone(zone).date()
    for offset in range(0, 370):
        candidates = {_civil_slot(day + timedelta(days=offset), slot, zone) for slot in rules.slots}
        later = [value for value in candidates if value > after]
        if later:
            return min(later)
    raise ValueError("no next slot")


def after_quiet(at_utc: datetime, tz: str, rules) -> datetime:
    instant = _utc(at_utc)
    if tz != rules.timezone:
        raise ValueError("timezone mismatch")
    zone = ZoneInfo(tz)
    local = instant.astimezone(zone)
    hhmm = local.strftime("%H:%M")
    start, end = rules.quiet_start, rules.quiet_end
    if start < end:
        quiet = start <= hhmm < end
        end_day = local.date()
    else:
        quiet = hhmm >= start or hhmm < end
        end_day = local.date() + timedelta(days=1) if hhmm >= start else local.date()
    if not quiet:
        return instant
    return max(instant, _civil_slot(end_day, end, zone))


def resume_deadline(clock, outage: dict, rules, now: datetime):
    """Record a confirmed outage and, once, extend a deadline it covered."""
    from .night_case_state import Clock, canonical_hash

    now = _utc(now)
    if type(outage) is not dict or set(outage) != {"outage_id", "unavailable_from", "resumed_at"}:
        raise ValueError("invalid outage")
    outage_id = outage["outage_id"]
    if not isinstance(outage_id, str) or not 1 <= len(outage_id) <= 120:
        raise ValueError("invalid outage id")
    start, resumed = _parse(outage["unavailable_from"]), _parse(outage["resumed_at"])
    if start > resumed or resumed != now:
        raise ValueError("outage time mismatch")
    fingerprint = canonical_hash(outage)
    data = clock.document()
    for prior in data["resume_receipts"]:
        if prior["outage_id"] == outage_id:
            if prior["payload_hash"] != fingerprint:
                raise ValueError("outage id conflict")
            return clock
    data["resume_receipts"].append({"outage_id": outage_id, "payload_hash": fingerprint})
    deadline = _parse(data["closes_at"]) if data["closes_at"] is not None else None
    if deadline is not None and start <= deadline <= resumed:
        duration = resumed - start
        seconds = min(rules.outage_extension_max_seconds, max(rules.outage_extension_min_seconds, duration.total_seconds()))
        data["closes_at"] = _stamp(after_quiet(now + timedelta(seconds=seconds), data["timezone"], rules))
        data["timer_seq"] += 1
    return Clock.from_document(data)
