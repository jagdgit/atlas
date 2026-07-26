"""IL.5+ — Atlas market holiday detection (hermetic)."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from atlas.trading.holidays import (
    add_operator_holiday,
    clear_operator_holidays,
    detect_holiday,
    holidays_view,
    is_holiday,
    list_holidays,
)
from atlas.trading.sessions import session_status


def setup_function() -> None:
    clear_operator_holidays()


def teardown_function() -> None:
    clear_operator_holidays()


def test_detect_republic_day_2026_on_nse():
    hol = detect_holiday("nse_equity", date(2026, 1, 26))
    assert hol is not None
    assert "Republic" in hol.name
    assert is_holiday("nse_fno", "2026-01-26")
    assert is_holiday("bse_equity", datetime(2026, 1, 26, 12, 0))


def test_session_closed_on_holiday_midday():
    now = datetime(2026, 1, 26, 12, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    st = session_status("nse_equity", now=now)
    assert st.open is False
    assert st.reason.startswith("holiday:")
    assert st.holiday and "Republic" in st.holiday


def test_session_open_on_ordinary_weekday():
    now = datetime(2026, 1, 27, 12, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    st = session_status("nse_equity", now=now)
    assert st.open is True
    assert st.reason == "regular_hours"
    assert st.holiday is None


def test_operator_overlay_detected():
    add_operator_holiday("india_equity", date(2026, 7, 22), "Special closure")
    hol = detect_holiday("nse_equity", date(2026, 7, 22))
    assert hol is not None
    assert hol.source == "operator"
    assert hol.name == "Special closure"
    now = datetime(2026, 7, 22, 11, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    st = session_status("nse_equity", now=now)
    assert st.open is False
    assert "Special closure" in (st.reason or "")


def test_list_holidays_2026_india():
    rows = list_holidays("india_equity", year=2026)
    assert len(rows) >= 15
    days = {h.day for h in rows}
    assert date(2026, 1, 15) in days  # MCGM election
    assert date(2026, 12, 25) in days


def test_us_thanksgiving_detected():
    hol = detect_holiday("us_equity", date(2026, 11, 26))
    assert hol is not None
    assert "Thanksgiving" in hol.name
    now = datetime(2026, 11, 26, 12, 0, tzinfo=ZoneInfo("America/New_York"))
    st = session_status("us_equity", now=now)
    assert st.open is False
    assert st.holiday == hol.name


def test_always_open_ignores_holidays():
    now = datetime(2026, 1, 26, 12, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    st = session_status("always_open", now=now)
    assert st.open is True


def test_holidays_view_shape():
    view = holidays_view(calendar_id="india_equity", year=2026, session_id="nse_equity")
    assert view["count"] >= 15
    assert view["calendar"] == "india_equity"
    assert any(h["day"] == "2026-01-26" for h in view["holidays"])
