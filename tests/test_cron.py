"""OI-A1: five-field crontab next-fire helper."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from atlas.scheduler.cron import CronError, is_cron_expr, next_run_after, parse_cron, validate_cron


def test_parse_every_minute():
    m, h, d, mo, w = parse_cron("* * * * *")
    assert len(m) == 60 and len(h) == 24


def test_next_run_hourly():
    after = datetime(2026, 7, 25, 10, 15, tzinfo=timezone.utc)
    nxt = next_run_after("0 * * * *", after=after)
    assert nxt == datetime(2026, 7, 25, 11, 0, tzinfo=timezone.utc)


def test_next_run_step_minutes():
    after = datetime(2026, 7, 25, 10, 2, tzinfo=timezone.utc)
    nxt = next_run_after("*/5 * * * *", after=after)
    assert nxt == datetime(2026, 7, 25, 10, 5, tzinfo=timezone.utc)


def test_next_run_weekday():
    # 2026-07-25 is Saturday (cron wd=6). Next Monday 09:30.
    after = datetime(2026, 7, 25, 8, 0, tzinfo=timezone.utc)
    nxt = next_run_after("30 9 * * 1-5", after=after)
    assert nxt == datetime(2026, 7, 27, 9, 30, tzinfo=timezone.utc)


def test_invalid_expr():
    with pytest.raises(CronError):
        validate_cron("not a cron")
    with pytest.raises(CronError):
        parse_cron("* * *")
    assert is_cron_expr("0 9 * * *") is True
    assert is_cron_expr("hourly") is False
