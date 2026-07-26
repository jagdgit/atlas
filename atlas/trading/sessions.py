"""Equity session calendars for paper-trading simulation (wall-clock gate).

Used so live (and optionally replay) ticks only buy/sell while the configured
market is open. Weekday + local open/close, plus **Atlas holiday detection**
(``atlas.trading.holidays``) for NSE/BSE/US sessions.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timezone
from typing import Callable
from zoneinfo import ZoneInfo

from atlas.trading.holidays import detect_holiday


@dataclass(frozen=True)
class MarketSession:
    """Regular equity session (Mon–Fri unless ``weekdays`` overridden)."""

    id: str
    timezone: str
    open_time: time
    close_time: time
    weekdays: frozenset[int] = frozenset({0, 1, 2, 3, 4})  # Mon–Fri


# Named sessions operators can set via ``PaperTradingConfig.market_session``.
_NSE_CASH = MarketSession(
    id="nse_equity",
    timezone="Asia/Kolkata",
    open_time=time(9, 15),
    close_time=time(15, 30),
)
SESSIONS: dict[str, MarketSession | None] = {
    "always_open": None,
    "nse_equity": _NSE_CASH,
    # Equity derivatives hours match cash on NSE.
    "nse_fno": MarketSession(
        id="nse_fno",
        timezone="Asia/Kolkata",
        open_time=time(9, 15),
        close_time=time(15, 30),
    ),
    "bse_equity": MarketSession(
        id="bse_equity",
        timezone="Asia/Kolkata",
        open_time=time(9, 15),
        close_time=time(15, 30),
    ),
    "us_equity": MarketSession(
        id="us_equity",
        timezone="America/New_York",
        open_time=time(9, 30),
        close_time=time(16, 0),
    ),
}


@dataclass(frozen=True)
class SessionStatus:
    session_id: str
    open: bool
    reason: str
    local_now: str | None = None
    holiday: str | None = None


def list_sessions() -> list[str]:
    return sorted(SESSIONS)


def get_session(session_id: str) -> MarketSession | None:
    """Return the session definition, or raise ``KeyError`` if unknown.

    ``always_open`` returns ``None`` (no clock gate).
    """
    key = (session_id or "always_open").strip().lower()
    if key not in SESSIONS:
        known = ", ".join(list_sessions())
        raise KeyError(f"unknown market_session {session_id!r} — known: {known}")
    return SESSIONS[key]


def session_status(
    session_id: str,
    *,
    now: datetime | None = None,
    clock: Callable[[], datetime] | None = None,
) -> SessionStatus:
    """Whether buys/sells are allowed under ``session_id`` at ``now``."""
    key = (session_id or "always_open").strip().lower()
    try:
        session = get_session(key)
    except KeyError as exc:
        return SessionStatus(session_id=key, open=False, reason=str(exc))

    if session is None:
        return SessionStatus(session_id=key, open=True, reason="always_open")

    instant = now
    if instant is None:
        instant = clock() if clock is not None else datetime.now(timezone.utc)
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)

    local = instant.astimezone(ZoneInfo(session.timezone))
    local_s = local.isoformat(timespec="minutes")
    if local.weekday() not in session.weekdays:
        return SessionStatus(
            session_id=key,
            open=False,
            reason="weekend",
            local_now=local_s,
        )

    hol = detect_holiday(key, local.date(), as_session=True)
    if hol is not None:
        return SessionStatus(
            session_id=key,
            open=False,
            reason=f"holiday:{hol.name}",
            local_now=local_s,
            holiday=hol.name,
        )

    t = local.timetz().replace(tzinfo=None)
    if t < session.open_time:
        return SessionStatus(
            session_id=key,
            open=False,
            reason="before_open",
            local_now=local_s,
        )
    if t >= session.close_time:
        return SessionStatus(
            session_id=key,
            open=False,
            reason="after_close",
            local_now=local_s,
        )
    return SessionStatus(
        session_id=key,
        open=True,
        reason="regular_hours",
        local_now=local_s,
    )


def is_session_open(
    session_id: str,
    *,
    now: datetime | None = None,
    clock: Callable[[], datetime] | None = None,
) -> bool:
    return session_status(session_id, now=now, clock=clock).open
