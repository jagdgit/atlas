"""OI-LINT0 Phase 3A — living market events (connect MTL / EVID / RSS).

Not a new news product. Empty stays unknown. Seeds and catalog summaries
are not evidence. LLM never invents headlines or analogue medians.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

VERSION = "lint0.market_events.v1"
_IST = ZoneInfo("Asia/Kolkata")

TIER_PRIMARY = 1
TIER_SECONDARY = 2
TIER_DISCOVERY = 3

ATTRIBUTION_CLASSES = (
    "causal",
    "likely",
    "possible",
    "unsupported",
    "unknown",
)

_PRIMARY_HINTS = (
    "pib",
    "rbi",
    "sebi",
    "nse",
    "bse",
    "mca.gov",
    "finmin",
    "incometax",
    "gstcouncil",
    "ministry",
    "gov.in",
    "nic.in",
    "exchange filing",
    "bseindia",
    "nseindia",
)
_SECONDARY_HOSTS = (
    "reuters.com",
    "bloomberg.com",
    "ft.com",
    "wsj.com",
    "livemint.com",
    "thehindubusinessline.com",
    "economist.com",
)
_FEED_TIER_1_IDS = frozenset({"pib_press", "rbi_press", "sebi_press"})
_CATALOG_PREFIXES = ("policy catalog items=", "policy/macro pulse items=")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def parse_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None

    def _aware(dt: datetime) -> datetime:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    if isinstance(value, datetime):
        return _aware(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return _aware(datetime.fromisoformat(text.replace("Z", "+00:00")))
    except ValueError:
        pass
    for fmt in (
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S GMT",
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M:%S",
    ):
        try:
            dt = datetime.strptime(text.replace("GMT", "+0000"), fmt)
            return _aware(dt)
        except ValueError:
            continue
    return None


def classify_source_tier(
    *,
    source: str | None = None,
    url: str | None = None,
    feed_id: str | None = None,
    kind: str | None = None,
) -> int | None:
    """IRA-style hierarchy: 1 primary · 2 secondary · 3 discovery only."""
    if not any(str(x or "").strip() for x in (source, url, feed_id)):
        return None
    fid = str(feed_id or "").strip().lower()
    if fid in _FEED_TIER_1_IDS:
        return TIER_PRIMARY
    blob = " ".join(
        str(x or "").lower() for x in (source, url, feed_id, kind)
    )
    host = ""
    if url:
        try:
            host = (urlparse(str(url)).hostname or "").lower()
        except Exception:  # noqa: BLE001
            host = ""
    if any(h in blob or h in host for h in _PRIMARY_HINTS):
        return TIER_PRIMARY
    if any(h in host or h in blob for h in _SECONDARY_HOSTS):
        return TIER_SECONDARY
    src = str(source or "").lower()
    if src in {"operator_input", "operator"}:
        return TIER_SECONDARY
    return TIER_DISCOVERY


def is_catalog_summary(row: dict[str, Any] | None) -> bool:
    if not isinstance(row, dict):
        return False
    pl = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    title = str(
        pl.get("title") or row.get("title") or pl.get("text") or row.get("text") or ""
    ).strip().lower()
    return any(title.startswith(p) for p in _CATALOG_PREFIXES) or bool(
        pl.get("catalog_summary") or row.get("catalog_summary")
    )


def may_become_evidence(row: dict[str, Any] | None) -> bool:
    """Tier 3 and catalog pulses never auto-write as evidence."""
    if not isinstance(row, dict):
        return False
    if is_catalog_summary(row):
        return False
    pl = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    if row.get("seed") or pl.get("seed"):
        return False
    if row.get("evidence_class") == "non_evidence" or pl.get("evidence_class") == "non_evidence":
        return False
    tier = pl.get("source_tier") or row.get("source_tier")
    try:
        t = int(tier) if tier is not None else None
    except (TypeError, ValueError):
        t = None
    if t == TIER_DISCOVERY:
        return False
    return True


def stamp_market_event(
    raw: dict[str, Any] | None,
    *,
    now: datetime | None = None,
    retrieved_at: str | None = None,
) -> dict[str, Any]:
    """Mandatory temporal + source fields. Missing published_at stays None (unknown)."""
    row = dict(raw or {})
    clock = now or _utcnow()
    observed = (
        parse_timestamp(row.get("observed_at"))
        or parse_timestamp(row.get("created_at"))
        or clock
    )
    published = parse_timestamp(
        row.get("published_at") or row.get("published") or row.get("pubDate")
    )
    valid_from = parse_timestamp(row.get("valid_from")) or published or observed
    valid_until = parse_timestamp(row.get("valid_until"))
    retrieved = retrieved_at or clock.isoformat()
    source = str(row.get("source") or "")
    url = str(row.get("link") or row.get("url") or "")
    feed_id = str(row.get("feed_id") or "")
    kind = str(row.get("kind") or row.get("event_class") or "")
    tier = row.get("source_tier")
    try:
        if tier is None or tier == "":
            tier_i = classify_source_tier(
                source=source, url=url, feed_id=feed_id, kind=kind
            )
        else:
            tier_i = int(tier)
    except (TypeError, ValueError):
        tier_i = classify_source_tier(source=source, url=url, feed_id=feed_id, kind=kind)
    if tier_i not in (TIER_PRIMARY, TIER_SECONDARY, TIER_DISCOVERY, None):
        tier_i = TIER_DISCOVERY
    evidence_class = row.get("evidence_class")
    if evidence_class is None:
        if row.get("seed") or is_catalog_summary(row):
            evidence_class = "non_evidence"
        elif tier_i == TIER_DISCOVERY:
            evidence_class = "research_question"
        elif tier_i is None:
            evidence_class = "unclassified"
        else:
            evidence_class = "evidence_candidate"
    out = dict(row)
    out.update(
        {
            "observed_at": observed.isoformat(),
            "published_at": published.isoformat() if published else None,
            "valid_from": valid_from.isoformat() if valid_from else None,
            "valid_until": valid_until.isoformat() if valid_until else None,
            "retrieved_at": retrieved,
            "source": source or "unknown",
            "source_tier": tier_i,
            "evidence_class": evidence_class,
            "event_class": kind or row.get("event_class") or "unclassified",
        }
    )
    return out


def usable_as_of(event: dict[str, Any], *, as_of: datetime | str | None) -> bool:
    """No future leakage: published/valid_from must be ≤ decision time when known."""
    if as_of is None:
        return True
    cutoff = parse_timestamp(as_of)
    if cutoff is None:
        return True
    pub = parse_timestamp(event.get("published_at") or event.get("valid_from"))
    if pub is None:
        return True
    return pub <= cutoff


def living_lane(
    events: list[dict[str, Any]] | None,
    *,
    as_of: datetime | str | None = None,
    max_age_days: int = 14,
    lane: str = "news",
) -> dict[str, Any]:
    """MTL/scientist lane: empty → unknown; stale catalog → stale; never invent."""
    as_of_dt = parse_timestamp(as_of) or _utcnow()
    kept: list[dict[str, Any]] = []
    for raw in events or []:
        if not isinstance(raw, dict):
            continue
        ev = stamp_market_event(raw, now=as_of_dt)
        if not may_become_evidence(ev):
            continue
        if not usable_as_of(ev, as_of=as_of_dt):
            continue
        kept.append(ev)
    if not kept:
        return {
            "status": "unknown",
            "missing": [lane],
            "count": 0,
            "freshness": "unknown",
            "items": [],
        }
    newest = None
    for ev in kept:
        ts = parse_timestamp(ev.get("published_at") or ev.get("observed_at"))
        if ts is None:
            continue
        if newest is None or ts > newest:
            newest = ts
    age_days = None
    if newest is not None:
        age_days = max(0.0, (as_of_dt - newest).total_seconds() / 86400.0)
    stale = age_days is not None and age_days > float(max_age_days)
    return {
        "status": "stale" if stale else "ok",
        "count": len(kept),
        "freshness": "stale" if stale else "living",
        "newest_at": newest.isoformat() if newest else None,
        "age_days": round(age_days, 2) if age_days is not None else None,
        "items": [
            {
                "title": str(e.get("title") or e.get("text") or "")[:160],
                "source": e.get("source"),
                "source_tier": e.get("source_tier"),
                "published_at": e.get("published_at"),
                "event_class": e.get("event_class"),
            }
            for e in kept[:6]
        ],
    }


def events_for_packet(
    *,
    news: list[dict[str, Any]] | None = None,
    policy: list[dict[str, Any]] | None = None,
    as_of: datetime | str | None = None,
) -> dict[str, Any]:
    news_lane = living_lane(news, as_of=as_of, lane="company_news")
    pol_lane = living_lane(policy, as_of=as_of, lane="policy_events")
    return {
        "news": news_lane["items"] or "unknown",
        "policy": pol_lane["items"] or "unknown",
        "news_freshness": news_lane.get("freshness"),
        "policy_freshness": pol_lane.get("freshness"),
        "news_status": news_lane.get("status"),
        "policy_status": pol_lane.get("status"),
    }


def classify_relative_move(
    *,
    name_ret_pct: float | None,
    nifty_ret_pct: float | None = None,
    sector_ret_pct: float | None = None,
    band_pct: float = 0.4,
) -> str:
    """Track D: vs market/sector, not 'news therefore good'."""
    if name_ret_pct is None:
        return "unknown"
    bench = sector_ret_pct if sector_ret_pct is not None else nifty_ret_pct
    if bench is None:
        return "unknown"
    delta = float(name_ret_pct) - float(bench)
    if abs(delta) <= band_pct:
        return "inline"
    return "outperform" if delta > 0 else "underperform"


def classify_attribution(
    *,
    event_present: bool,
    expected_sign: int | None = None,
    actual_sign: int | None = None,
    relative: str | None = None,
    evidence_tier: int | None = None,
    event_before_move: bool | None = None,
) -> str:
    """Never news-up ⇒ news caused it. Unknown stays unknown."""
    if not event_present:
        return "unknown"
    if event_before_move is False:
        return "unsupported"
    if expected_sign is None or actual_sign is None:
        return "unknown"
    if expected_sign == 0 or actual_sign == 0:
        return "unsupported" if expected_sign != actual_sign else "possible"
    agree = (expected_sign > 0) == (actual_sign > 0)
    rel = str(relative or "")
    tier = int(evidence_tier or TIER_DISCOVERY)
    if not agree:
        return "unsupported"
    if event_before_move is True and tier == TIER_PRIMARY and rel in {"outperform", "underperform", "inline"}:
        return "likely"
    if event_before_move is True and tier <= TIER_SECONDARY:
        return "possible"
    return "unknown"


def analogue_distribution(returns_pct: list[float] | None) -> dict[str, Any]:
    """Honest distribution. LLM must not invent the median."""
    xs = [float(x) for x in (returns_pct or []) if x is not None]
    n = len(xs)
    if n < 5:
        return {
            "status": "unknown",
            "n": n,
            "reason": "insufficient_analogues",
            "horizon_note": "need n≥5 similar windows",
        }
    xs.sort()
    mid = xs[n // 2] if n % 2 else 0.5 * (xs[n // 2 - 1] + xs[n // 2])
    mean = sum(xs) / n
    var = sum((x - mean) ** 2 for x in xs) / n
    std = math.sqrt(var)
    p25 = xs[max(0, (n * 1) // 4)]
    p75 = xs[min(n - 1, (n * 3) // 4)]
    iqr = p75 - p25
    dispersion = "wide" if iqr >= 8.0 or std >= 6.0 else "moderate" if iqr >= 3.0 else "tight"
    return {
        "status": "ok",
        "n": n,
        "median_pct": round(mid, 2),
        "p25_pct": round(p25, 2),
        "p75_pct": round(p75, 2),
        "std_pct": round(std, 2),
        "dispersion": dispersion,
        "honesty": "distribution from similar past windows — not a point forecast",
    }


def rsi_regime_analogues(
    closes: list[float],
    *,
    rsi_n: int = 14,
    horizon: int = 20,
    band: float = 8.0,
    min_n: int = 5,
) -> dict[str, Any]:
    """Price-regime analogue from bars. Event-class analogues stay unknown until tagged."""
    if len(closes) < rsi_n + horizon + 2:
        return analogue_distribution([])
    rsis: list[float | None] = [None] * len(closes)

    def _rsi_at(i: int) -> float | None:
        if i < rsi_n:
            return None
        gains = 0.0
        losses = 0.0
        for j in range(i - rsi_n + 1, i + 1):
            d = closes[j] - closes[j - 1]
            if d >= 0:
                gains += d
            else:
                losses -= d
        if losses == 0:
            return 100.0
        rs = (gains / rsi_n) / (losses / rsi_n)
        return 100.0 - (100.0 / (1.0 + rs))

    for i in range(rsi_n, len(closes)):
        rsis[i] = _rsi_at(i)
    now_i = len(closes) - 1
    now_rsi = rsis[now_i]
    if now_rsi is None:
        return analogue_distribution([])
    fwd: list[float] = []
    last_ok = len(closes) - 1 - horizon
    for i in range(rsi_n, last_ok):
        r = rsis[i]
        if r is None:
            continue
        if abs(r - now_rsi) > band:
            continue
        prev = closes[i]
        later = closes[i + horizon]
        if prev == 0:
            continue
        fwd.append(100.0 * (later - prev) / abs(prev))
    out = analogue_distribution(fwd if len(fwd) >= min_n else [])
    out["basis"] = "rsi_regime"
    out["rsi_now"] = round(float(now_rsi), 2)
    out["horizon_bars"] = horizon
    if out.get("status") == "unknown":
        out["event_class_analogues"] = "unknown"
    return out
