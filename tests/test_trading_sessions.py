"""Hermetic tests for equity session calendars (paper-trading market-hours gate)."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from atlas.trading.sessions import is_session_open, list_sessions, session_status


def test_always_open():
    assert is_session_open("always_open") is True
    st = session_status("always_open")
    assert st.open and st.reason == "always_open"


def test_nse_open_midday_weekday():
    # Wednesday 2024-01-10 12:00 IST
    now = datetime(2024, 1, 10, 12, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    st = session_status("nse_equity", now=now)
    assert st.open is True
    assert st.reason == "regular_hours"


def test_nse_closed_before_open():
    now = datetime(2024, 1, 10, 9, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    st = session_status("nse_equity", now=now)
    assert st.open is False
    assert st.reason == "before_open"


def test_nse_closed_after_close():
    now = datetime(2024, 1, 10, 15, 30, tzinfo=ZoneInfo("Asia/Kolkata"))
    st = session_status("nse_equity", now=now)
    assert st.open is False
    assert st.reason == "after_close"


def test_nse_weekend():
    # Saturday
    now = datetime(2024, 1, 13, 12, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    st = session_status("nse_equity", now=now)
    assert st.open is False
    assert st.reason == "weekend"


def test_us_equity_open():
    now = datetime(2024, 1, 10, 10, 0, tzinfo=ZoneInfo("America/New_York"))
    assert is_session_open("us_equity", now=now) is True


def test_unknown_session():
    st = session_status("martian_exchange")
    assert st.open is False
    assert "unknown" in st.reason


def test_list_sessions_includes_nse_and_us():
    names = list_sessions()
    assert "nse_equity" in names
    assert "us_equity" in names
    assert "always_open" in names
