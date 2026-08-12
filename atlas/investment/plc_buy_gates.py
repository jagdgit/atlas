"""PLC.A — buy quality gates: fundamental sanity + explicit thesis trigger.

Keeps SMA/RSI as the technical control trigger (A1). These gates are additive,
fail-closed for learner books when enabled, and never invent missing fields.
"""

from __future__ import annotations

import re
from typing import Any

VERSION = "plc.a.buy_gates"

# Boilerplate / technical-only phrases that do NOT count as a thesis trigger
_WEAK_TRIGGER = re.compile(
    r"^\s*("
    r"researched(?:\s*\(.*\))?|"
    r"mvr(?:\s*/\s*coverage)?|"
    r"sma(?:\d+)?(?:\s*/\s*rsi)?|"
    r"rsi|"
    r"quality\s+proxy|"
    r"policy\s+prefer(?:ence|/?\s*trust)?|"
    r"positive\s+quality\s+proxy|"
    r"momentum|"
    r"liquidity|"
    r"learning\s*[—\-].*|"
    r"insufficient\b.*"
    r")\s*$",
    re.IGNORECASE,
)
_TECHNICAL_ONLY = re.compile(
    r"\b(sma\d*|rsi|crossover|crossunder|overbought|oversold)\b",
    re.IGNORECASE,
)


def plc_a_enabled(cfg: dict[str, Any] | None, portfolio_key: str | None) -> bool:
    """Learner books default ON; other books OFF unless cfg forces."""
    cfg = cfg or {}
    if cfg.get("plc_a_gates") is not None:
        return bool(cfg.get("plc_a_gates"))
    if cfg.get("plc_a_buy_gates") is not None:
        return bool(cfg.get("plc_a_buy_gates"))
    pk = (portfolio_key or "").lower()
    return "learner" in pk or "laboratory" in pk


def _f(row: dict[str, Any] | None, *keys: str) -> Any:
    if not isinstance(row, dict):
        return None
    for k in keys:
        if row.get(k) is not None:
            return row.get(k)
    return None


def sector_from_sources(
    *,
    instrument_sector: str | None = None,
    fundamentals: dict[str, Any] | None = None,
    awareness: dict[str, Any] | None = None,
) -> str | None:
    for raw in (
        instrument_sector,
        (fundamentals or {}).get("sector"),
        (awareness or {}).get("sector"),
        ((awareness or {}).get("identity") or {}).get("sector")
        if isinstance((awareness or {}).get("identity"), dict)
        else None,
        ((awareness or {}).get("business_identity") or {}).get("sector")
        if isinstance((awareness or {}).get("business_identity"), dict)
        else None,
    ):
        s = str(raw or "").strip()
        if s and s.lower() not in {"unknown", "n/a", "none", "?"}:
            return s
    # dossier-shaped awareness
    thesis = (awareness or {}).get("thesis") if isinstance(awareness, dict) else None
    if isinstance(thesis, dict):
        sec = str(thesis.get("sector") or "").strip()
        if sec and sec.lower() != "unknown":
            return sec
    return None


def evaluate_fundamental_sanity(
    fundamentals: dict[str, Any] | None,
    *,
    sector: str | None,
) -> dict[str, Any]:
    """A2 — PE, ROE, D/E present and sector identified."""
    missing: list[str] = []
    pe = _f(fundamentals, "pe", "trailing_pe")
    roe = _f(fundamentals, "roe")
    de = _f(fundamentals, "debt_to_equity", "debt_equity", "de")
    if pe is None:
        missing.append("pe")
    if roe is None:
        missing.append("roe")
    if de is None:
        missing.append("debt_to_equity")
    sector_ok = bool(sector and str(sector).strip())
    if not sector_ok:
        missing.append("sector")
    if missing:
        code = "sector_unknown" if missing == ["sector"] else "fundamentals_incomplete"
        return {
            "ok": False,
            "code": code,
            "missing": missing,
            "sector": sector,
            "reason": f"{code}:" + ",".join(missing),
        }
    return {
        "ok": True,
        "code": "fundamentals_ok",
        "missing": [],
        "sector": sector,
        "reason": None,
    }


def _clean_trigger(text: str | None) -> str | None:
    t = " ".join(str(text or "").split()).strip()
    if len(t) < 16:
        return None
    if _WEAK_TRIGGER.match(t):
        return None
    # Reject pure technical lines
    if _TECHNICAL_ONLY.search(t) and not re.search(
        r"\b(because|occupancy|pricing|export|capex|credit|arpu|demand|"
        r"margin|mix|policy|hospital|pharma|telecom|motorcycle|brand)\b",
        t,
        re.I,
    ):
        return None
    return t[:220]


def extract_thesis_trigger(
    *,
    awareness: dict[str, Any] | None = None,
    engine_why: str | None = None,
) -> dict[str, Any]:
    """A3 — one explicit sector-aware reason (not 'researched' / SMA-only)."""
    aw = awareness if isinstance(awareness, dict) else {}
    candidates: list[str] = []

    dist = aw.get("thesis_distinctiveness") or aw.get("distinctiveness")
    if isinstance(dist, dict):
        for vd in dist.get("value_drivers") or []:
            if isinstance(vd, str):
                candidates.append(vd)
            elif isinstance(vd, dict) and vd.get("text"):
                candidates.append(str(vd["text"]))
        for reason in dist.get("reasons") or []:
            if isinstance(reason, str):
                candidates.append(reason)

    thesis = aw.get("thesis") if isinstance(aw.get("thesis"), dict) else {}
    for key in ("summary", "hypothesis", "one_liner", "trigger"):
        if thesis.get(key):
            candidates.append(str(thesis.get(key)))
    for d in thesis.get("drivers") or []:
        if isinstance(d, str):
            candidates.append(d)
        elif isinstance(d, dict) and (d.get("text") or d.get("driver")):
            candidates.append(str(d.get("text") or d.get("driver")))

    tracker = aw.get("thesis_tracker") if isinstance(aw.get("thesis_tracker"), dict) else {}
    if tracker.get("hypothesis"):
        candidates.append(str(tracker["hypothesis"]))

    for key in ("thesis_drivers", "summary"):
        val = aw.get(key)
        if isinstance(val, str):
            candidates.append(val)
        elif isinstance(val, list):
            candidates.extend(str(x) for x in val if x)

    # Engine why last — usually SMA; only keep if it carries a business clause
    if engine_why:
        candidates.append(str(engine_why))

    for raw in candidates:
        cleaned = _clean_trigger(raw)
        if cleaned:
            return {
                "ok": True,
                "code": "thesis_trigger_ok",
                "trigger": cleaned,
                "reason": None,
            }
    return {
        "ok": False,
        "code": "thesis_trigger_missing",
        "trigger": None,
        "reason": "thesis_trigger_missing",
    }


def evaluate_plc_a_buy(
    *,
    fundamentals: dict[str, Any] | None,
    awareness: dict[str, Any] | None,
    instrument_sector: str | None = None,
    engine_why: str | None = None,
    require_fundamentals: bool = True,
    require_thesis_trigger: bool = True,
) -> dict[str, Any]:
    """Combine A2 + A3. Returns block details when not allowed."""
    sector = sector_from_sources(
        instrument_sector=instrument_sector,
        fundamentals=fundamentals,
        awareness=awareness,
    )
    fund = (
        evaluate_fundamental_sanity(fundamentals, sector=sector)
        if require_fundamentals
        else {"ok": True, "code": "fundamentals_skipped", "missing": [], "sector": sector}
    )
    thesis = (
        extract_thesis_trigger(awareness=awareness, engine_why=engine_why)
        if require_thesis_trigger
        else {"ok": True, "code": "thesis_skipped", "trigger": None}
    )

    blocks: list[str] = []
    strategy_tag = "plc_a_ok"
    if not fund.get("ok"):
        blocks.append(str(fund.get("reason") or "fundamentals_incomplete"))
        strategy_tag = str(fund.get("code") or "fundamentals_incomplete")
    if not thesis.get("ok"):
        blocks.append(str(thesis.get("reason") or "thesis_trigger_missing"))
        if strategy_tag == "plc_a_ok":
            strategy_tag = "thesis_trigger_missing"

    allowed = not blocks
    return {
        "version": VERSION,
        "allowed": allowed,
        "strategy_tag": strategy_tag if not allowed else "sma_cross_rsi",
        "blocks": blocks,
        "fundamentals": fund,
        "thesis": thesis,
        "thesis_trigger": thesis.get("trigger"),
        "sector": sector,
        "honesty": (
            "PLC.A: SMA/RSI remains technical trigger; PE/ROE/D/E + sector + "
            "explicit thesis reason required for learner buys when enabled."
        ),
    }
