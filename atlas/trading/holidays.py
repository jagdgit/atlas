"""Market holiday detection for Decision Simulation session gates (IL.5+).

Atlas detects exchange holidays from **built-in calendars** curated from published
NSE/BSE/NYSE circulars — applied automatically by ``session_status`` (no operator
config required). Not a live scrape; operators can overlay extra closed days.

Muhurat / special sessions are treated as **full-day closed** for regular cash
session gates (conservative sim).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Any

# Session id → Atlas calendar id
SESSION_CALENDARS: dict[str, str] = {
    "nse_equity": "india_equity",
    "nse_fno": "india_equity",
    "bse_equity": "india_equity",
    "us_equity": "us_equity",
}


@dataclass(frozen=True)
class MarketHoliday:
    """One exchange closed day Atlas knows about."""

    day: date
    name: str
    calendar: str
    source: str = "atlas_seed"

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["day"] = self.day.isoformat()
        return d


def _h(calendar: str, y: int, m: int, d: int, name: str) -> MarketHoliday:
    return MarketHoliday(day=date(y, m, d), name=name, calendar=calendar, source="atlas_seed")


# --- India equity (NSE + BSE cash / F&O regular session) -------------------
# Weekday trading holidays from exchange circulars. Weekend-only observances omitted.
_INDIA: tuple[MarketHoliday, ...] = (
    # 2024
    _h("india_equity", 2024, 1, 26, "Republic Day"),
    _h("india_equity", 2024, 3, 8, "Mahashivratri"),
    _h("india_equity", 2024, 3, 25, "Holi"),
    _h("india_equity", 2024, 3, 29, "Good Friday"),
    _h("india_equity", 2024, 4, 11, "Id-Ul-Fitr"),
    _h("india_equity", 2024, 4, 17, "Ram Navami"),
    _h("india_equity", 2024, 5, 1, "Maharashtra Day"),
    _h("india_equity", 2024, 6, 17, "Bakri Id"),
    _h("india_equity", 2024, 7, 17, "Muharram"),
    _h("india_equity", 2024, 8, 15, "Independence Day"),
    _h("india_equity", 2024, 10, 2, "Mahatma Gandhi Jayanti"),
    _h("india_equity", 2024, 11, 1, "Diwali Laxmi Pujan"),
    _h("india_equity", 2024, 11, 15, "Gurunanak Jayanti"),
    _h("india_equity", 2024, 12, 25, "Christmas"),
    # 2025
    _h("india_equity", 2025, 2, 26, "Mahashivratri"),
    _h("india_equity", 2025, 3, 14, "Holi"),
    _h("india_equity", 2025, 3, 31, "Id-Ul-Fitr"),
    _h("india_equity", 2025, 4, 10, "Mahavir Jayanti"),
    _h("india_equity", 2025, 4, 14, "Dr. Baba Saheb Ambedkar Jayanti"),
    _h("india_equity", 2025, 4, 18, "Good Friday"),
    _h("india_equity", 2025, 5, 1, "Maharashtra Day"),
    _h("india_equity", 2025, 8, 15, "Independence Day"),
    _h("india_equity", 2025, 8, 27, "Ganesh Chaturthi"),
    _h("india_equity", 2025, 10, 2, "Mahatma Gandhi Jayanti / Dussehra"),
    _h("india_equity", 2025, 10, 21, "Diwali Laxmi Pujan"),
    _h("india_equity", 2025, 10, 22, "Diwali-Balipratipada"),
    _h("india_equity", 2025, 11, 5, "Prakash Gurpurb Sri Guru Nanak Dev"),
    _h("india_equity", 2025, 12, 25, "Christmas"),
    # 2026 (NSE/BSE equity + equity derivatives)
    _h("india_equity", 2026, 1, 15, "Municipal Corporation Election - Maharashtra"),
    _h("india_equity", 2026, 1, 26, "Republic Day"),
    _h("india_equity", 2026, 3, 3, "Holi"),
    _h("india_equity", 2026, 3, 26, "Shri Ram Navami"),
    _h("india_equity", 2026, 3, 31, "Shri Mahavir Jayanti"),
    _h("india_equity", 2026, 4, 3, "Good Friday"),
    _h("india_equity", 2026, 4, 14, "Dr. Baba Saheb Ambedkar Jayanti"),
    _h("india_equity", 2026, 5, 1, "Maharashtra Day"),
    _h("india_equity", 2026, 5, 28, "Bakri Id"),
    _h("india_equity", 2026, 6, 26, "Muharram"),
    _h("india_equity", 2026, 9, 14, "Ganesh Chaturthi"),
    _h("india_equity", 2026, 10, 2, "Mahatma Gandhi Jayanti"),
    _h("india_equity", 2026, 10, 20, "Dussehra"),
    _h("india_equity", 2026, 11, 10, "Diwali-Balipratipada"),
    _h("india_equity", 2026, 11, 24, "Prakash Gurpurb Sri Guru Nanak Dev"),
    _h("india_equity", 2026, 12, 25, "Christmas"),
)

# --- US equity (NYSE regular session; major closes) ------------------------
_US: tuple[MarketHoliday, ...] = (
    _h("us_equity", 2024, 1, 1, "New Year's Day"),
    _h("us_equity", 2024, 1, 15, "Martin Luther King Jr. Day"),
    _h("us_equity", 2024, 2, 19, "Presidents' Day"),
    _h("us_equity", 2024, 3, 29, "Good Friday"),
    _h("us_equity", 2024, 5, 27, "Memorial Day"),
    _h("us_equity", 2024, 6, 19, "Juneteenth"),
    _h("us_equity", 2024, 7, 4, "Independence Day"),
    _h("us_equity", 2024, 9, 2, "Labor Day"),
    _h("us_equity", 2024, 11, 28, "Thanksgiving"),
    _h("us_equity", 2024, 12, 25, "Christmas"),
    _h("us_equity", 2025, 1, 1, "New Year's Day"),
    _h("us_equity", 2025, 1, 20, "Martin Luther King Jr. Day"),
    _h("us_equity", 2025, 2, 17, "Presidents' Day"),
    _h("us_equity", 2025, 4, 18, "Good Friday"),
    _h("us_equity", 2025, 5, 26, "Memorial Day"),
    _h("us_equity", 2025, 6, 19, "Juneteenth"),
    _h("us_equity", 2025, 7, 4, "Independence Day"),
    _h("us_equity", 2025, 9, 1, "Labor Day"),
    _h("us_equity", 2025, 11, 27, "Thanksgiving"),
    _h("us_equity", 2025, 12, 25, "Christmas"),
    _h("us_equity", 2026, 1, 1, "New Year's Day"),
    _h("us_equity", 2026, 1, 19, "Martin Luther King Jr. Day"),
    _h("us_equity", 2026, 2, 16, "Presidents' Day"),
    _h("us_equity", 2026, 4, 3, "Good Friday"),
    _h("us_equity", 2026, 5, 25, "Memorial Day"),
    _h("us_equity", 2026, 6, 19, "Juneteenth"),
    _h("us_equity", 2026, 7, 3, "Independence Day (observed)"),
    _h("us_equity", 2026, 9, 7, "Labor Day"),
    _h("us_equity", 2026, 11, 26, "Thanksgiving"),
    _h("us_equity", 2026, 12, 25, "Christmas"),
)

_SEED: dict[str, dict[date, MarketHoliday]] = {}
for _row in (*_INDIA, *_US):
    _SEED.setdefault(_row.calendar, {})[_row.day] = _row

# Operator overlays (tests / POST) — never wipe seeds
_OPERATOR: dict[str, dict[date, MarketHoliday]] = {}


def list_calendars() -> list[dict[str, Any]]:
    return [
        {
            "id": "india_equity",
            "label": "NSE/BSE equity & F&O (regular session)",
            "sessions": sorted(s for s, c in SESSION_CALENDARS.items() if c == "india_equity"),
            "years": sorted({d.year for d in _SEED.get("india_equity", {})}),
            "source": "atlas_seed",
        },
        {
            "id": "us_equity",
            "label": "US equity (NYSE-style)",
            "sessions": sorted(s for s, c in SESSION_CALENDARS.items() if c == "us_equity"),
            "years": sorted({d.year for d in _SEED.get("us_equity", {})}),
            "source": "atlas_seed",
        },
    ]


def calendar_for_session(session_id: str | None) -> str | None:
    key = (session_id or "").strip().lower()
    return SESSION_CALENDARS.get(key)


def _as_date(value: date | datetime | str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if "T" in text:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    return date.fromisoformat(text[:10])


def detect_holiday(
    session_or_calendar: str,
    when: date | datetime | str,
    *,
    as_session: bool = True,
) -> MarketHoliday | None:
    """Return the holiday Atlas detects for this session/calendar on ``when``, else None."""
    key = (session_or_calendar or "").strip().lower()
    cal = calendar_for_session(key) if as_session else key
    if as_session and cal is None:
        # Allow passing calendar id directly
        if key in _SEED or key in _OPERATOR:
            cal = key
        else:
            return None
    if not cal:
        return None
    day = _as_date(when)
    op = _OPERATOR.get(cal, {}).get(day)
    if op is not None:
        return op
    return _SEED.get(cal, {}).get(day)


def is_holiday(
    session_or_calendar: str,
    when: date | datetime | str,
    *,
    as_session: bool = True,
) -> bool:
    return detect_holiday(session_or_calendar, when, as_session=as_session) is not None


def list_holidays(
    calendar_id: str = "india_equity",
    *,
    year: int | None = None,
) -> list[MarketHoliday]:
    """List seed + operator holidays for a calendar (optionally one year)."""
    cal = (calendar_id or "india_equity").strip().lower()
    merged: dict[date, MarketHoliday] = dict(_SEED.get(cal, {}))
    merged.update(_OPERATOR.get(cal, {}))
    rows = sorted(merged.values(), key=lambda h: h.day)
    if year is not None:
        rows = [h for h in rows if h.day.year == int(year)]
    return rows


def add_operator_holiday(
    calendar_id: str,
    day: date | datetime | str,
    name: str,
) -> MarketHoliday:
    """Overlay a closed day Atlas should detect (tests / operator)."""
    cal = (calendar_id or "").strip().lower() or "india_equity"
    hol = MarketHoliday(
        day=_as_date(day),
        name=(name or "operator_holiday").strip() or "operator_holiday",
        calendar=cal,
        source="operator",
    )
    _OPERATOR.setdefault(cal, {})[hol.day] = hol
    return hol


def clear_operator_holidays(calendar_id: str | None = None) -> None:
    if calendar_id is None:
        _OPERATOR.clear()
        return
    _OPERATOR.pop((calendar_id or "").strip().lower(), None)


def holidays_view(
    *,
    calendar_id: str = "india_equity",
    year: int | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    cal = calendar_id
    if session_id:
        mapped = calendar_for_session(session_id)
        if mapped:
            cal = mapped
    rows = list_holidays(cal, year=year)
    return {
        "calendar": cal,
        "session_id": session_id,
        "year": year,
        "holidays": [h.as_dict() for h in rows],
        "count": len(rows),
        "calendars": list_calendars(),
        "note": (
            "Atlas detects these closed days automatically in market_session gates; "
            "seeded from exchange circulars (not a live scrape)."
        ),
        "version": "il.5.holidays",
    }


def seed_years(calendar_id: str = "india_equity") -> list[int]:
    return sorted({d.year for d in _SEED.get(calendar_id, {})})


__all__ = [
    "MarketHoliday",
    "SESSION_CALENDARS",
    "add_operator_holiday",
    "calendar_for_session",
    "clear_operator_holidays",
    "detect_holiday",
    "holidays_view",
    "is_holiday",
    "list_calendars",
    "list_holidays",
    "seed_years",
]
