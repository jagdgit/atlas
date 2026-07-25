"""Five-field crontab next-fire helper (OI-A1).

Supports standard ``minute hour day month weekday`` expressions with ``*``,
lists (``,``), ranges (``-``), and steps (``/``). No external dependency —
extends the existing ``scheduler.schedules`` path rather than inventing a
parallel cron daemon.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


class CronError(ValueError):
    """Invalid crontab expression."""


def _parse_field(field: str, lo: int, hi: int) -> frozenset[int]:
    text = (field or "").strip()
    if not text:
        raise CronError(f"empty cron field (expected {lo}-{hi})")
    values: set[int] = set()
    for part in text.split(","):
        part = part.strip()
        if not part:
            raise CronError(f"empty list entry in cron field {field!r}")
        step = 1
        if "/" in part:
            base, step_s = part.split("/", 1)
            try:
                step = int(step_s)
            except ValueError as exc:
                raise CronError(f"bad step in {part!r}") from exc
            if step < 1:
                raise CronError(f"step must be >= 1 in {part!r}")
            part = base if base else "*"
        if part == "*":
            start, end = lo, hi
        elif "-" in part:
            a_s, b_s = part.split("-", 1)
            try:
                start, end = int(a_s), int(b_s)
            except ValueError as exc:
                raise CronError(f"bad range in {part!r}") from exc
        else:
            try:
                start = end = int(part)
            except ValueError as exc:
                raise CronError(f"bad value in {part!r}") from exc
        if start > end or start < lo or end > hi:
            raise CronError(f"out of range {start}-{end} for {lo}-{hi} in {field!r}")
        values.update(range(start, end + 1, step))
    if not values:
        raise CronError(f"no values matched in cron field {field!r}")
    return frozenset(values)


def parse_cron(expr: str) -> tuple[frozenset[int], frozenset[int], frozenset[int], frozenset[int], frozenset[int]]:
    """Parse a 5-field crontab into (minute, hour, day, month, weekday) sets.

    Weekday: ``0`` and ``7`` are Sunday (cron convention).
    """
    parts = (expr or "").strip().split()
    if len(parts) != 5:
        raise CronError(f"expected 5 fields, got {len(parts)} in {expr!r}")
    minutes = _parse_field(parts[0], 0, 59)
    hours = _parse_field(parts[1], 0, 23)
    days = _parse_field(parts[2], 1, 31)
    months = _parse_field(parts[3], 1, 12)
    raw_wd = _parse_field(parts[4], 0, 7)
    weekdays = frozenset(0 if d == 7 else d for d in raw_wd)
    return minutes, hours, days, months, weekdays


def _matches(
    dt: datetime,
    minutes: frozenset[int],
    hours: frozenset[int],
    days: frozenset[int],
    months: frozenset[int],
    weekdays: frozenset[int],
) -> bool:
    # Cron OR semantics when both day-of-month and day-of-week are restricted:
    # match if either field matches (standard Vixie cron). Python weekday is
    # Mon=0..Sun=6; cron weekday is Sun=0..Sat=6.
    cron_wd = (dt.weekday() + 1) % 7
    day_star = days == frozenset(range(1, 32))
    wd_star = weekdays == frozenset(range(0, 7))
    if day_star and wd_star:
        day_ok = True
    elif day_star:
        day_ok = cron_wd in weekdays
    elif wd_star:
        day_ok = dt.day in days
    else:
        day_ok = dt.day in days or cron_wd in weekdays
    return (
        dt.minute in minutes
        and dt.hour in hours
        and dt.month in months
        and day_ok
    )


def next_run_after(expr: str, after: datetime | None = None) -> datetime:
    """Return the next UTC fire time strictly after ``after`` (default: now).

    Searches minute-by-minute up to ~2 years ahead so pathological expressions
    fail loudly rather than hanging forever.
    """
    minutes, hours, days, months, weekdays = parse_cron(expr)
    if after is None:
        after = datetime.now(timezone.utc)
    elif after.tzinfo is None:
        after = after.replace(tzinfo=timezone.utc)
    else:
        after = after.astimezone(timezone.utc)

    # Start at the next whole minute.
    cursor = (after + timedelta(minutes=1)).replace(second=0, microsecond=0)
    limit = cursor + timedelta(days=366 * 2)
    while cursor <= limit:
        if cursor.month in months and _matches(
            cursor, minutes, hours, days, months, weekdays
        ):
            return cursor
        cursor += timedelta(minutes=1)
    raise CronError(f"no fire time within 2 years for {expr!r}")


def is_cron_expr(text: str | None) -> bool:
    """True when ``text`` looks like a 5-field crontab (for cadence hints)."""
    if not text or not str(text).strip():
        return False
    parts = str(text).strip().split()
    if len(parts) != 5:
        return False
    try:
        parse_cron(text)
        return True
    except CronError:
        return False


def validate_cron(expr: str) -> str:
    """Normalize/validate; returns stripped expr or raises :class:`CronError`."""
    text = (expr or "").strip()
    parse_cron(text)
    return text
