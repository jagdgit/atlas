"""F&O RT attribution from durable market/option observables — never invent.

Statuses (cause ladder; does not validate lessons / L5):
  unknown_explicit — looked; no usable underlying/premium path evidence
  partial          — some factors labeled from evidence; material unknowns remain
  evidence_backed  — underlying + premium path durable and direction-aligned labels

Cognitive Core may *interpret* this evidence pack. It must not invent IV/delta/news.
Belief update / strategy mutation stay off until gates say otherwise.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VERSION = "fno.option_attribution.v1"

STATUS_UNKNOWN = "unknown_explicit"
STATUS_PARTIAL = "partial"
STATUS_EVIDENCE_BACKED = "evidence_backed"

_PX_EPS = 0.15  # % — below this, underlying path too small to label helped/hurt


def _f(x: Any) -> float | None:
    try:
        if x is None or x == "":
            return None
        return float(x)
    except (TypeError, ValueError):
        return None


def _parse_ts(raw: Any) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    s = str(raw).strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _ist_date(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    try:
        from zoneinfo import ZoneInfo

        return dt.astimezone(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d")
    except Exception:  # noqa: BLE001
        return dt.strftime("%Y-%m-%d")


def normalize_underlying_bar_symbol(underlying: str | None) -> str:
    u = str(underlying or "").strip().upper()
    if not u:
        return ""
    if u.endswith(".NS") or u.endswith(".BO"):
        return u
    # Index underliers use different Yahoo symbols — leave bare for caller.
    if u in {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"}:
        return u
    return f"{u}.NS"


def load_underlying_daily_bar(
    data_dir: str | Path | None,
    underlying: str | None,
    *,
    as_of_ist: str | None = None,
) -> dict[str, Any] | None:
    """Durable daily OHLCV for underlier on as_of_ist (fail-closed)."""
    if not data_dir or not underlying:
        return None
    sym = normalize_underlying_bar_symbol(underlying)
    path = Path(data_dir) / "market" / "bars" / f"{sym}.json"
    if not path.is_file():
        # try bare
        bare = str(underlying or "").strip().upper()
        alt = Path(data_dir) / "market" / "bars" / f"{bare}.json"
        path = alt if alt.is_file() else path
    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    bars = doc.get("bars") if isinstance(doc, dict) else None
    if not isinstance(bars, list) or not bars:
        return None
    day = str(as_of_ist or "").strip()[:10]
    if day:
        for b in reversed(bars):
            if isinstance(b, dict) and str(b.get("date") or "")[:10] == day:
                return dict(b)
    last = bars[-1] if isinstance(bars[-1], dict) else None
    return dict(last) if last else None


def build_fno_rt_evidence(
    *,
    underlying: str | None,
    option_symbol: str | None = None,
    option_right: str | None = None,
    entry_premium: float | None = None,
    exit_premium: float | None = None,
    entry_time: Any = None,
    exit_time: Any = None,
    realized_pnl: float | None = None,
    prediction_error: dict[str, Any] | None = None,
    data_dir: str | Path | None = None,
    as_of_ist: str | None = None,
    mark_source: str | None = None,
) -> dict[str, Any]:
    """Observable evidence pack for one session_flat option RT."""
    right = str(option_right or "").strip().upper() or None
    entry_px = _f(entry_premium)
    exit_px = _f(exit_premium)
    entry_dt = _parse_ts(entry_time)
    exit_dt = _parse_ts(exit_time)
    day = as_of_ist or _ist_date(exit_dt) or _ist_date(entry_dt)

    premium_ret_pct: float | None = None
    if entry_px is not None and exit_px is not None and abs(entry_px) > 1e-12:
        premium_ret_pct = 100.0 * (exit_px - entry_px) / abs(entry_px)

    hold_minutes: float | None = None
    if entry_dt and exit_dt:
        hold_minutes = max(0.0, (exit_dt - entry_dt).total_seconds() / 60.0)

    und_bar = load_underlying_daily_bar(data_dir, underlying, as_of_ist=day)
    und_open = _f((und_bar or {}).get("open"))
    und_close = _f((und_bar or {}).get("close"))
    und_high = _f((und_bar or {}).get("high"))
    und_low = _f((und_bar or {}).get("low"))
    und_ret_pct: float | None = None
    if und_open is not None and und_close is not None and abs(und_open) > 1e-12:
        und_ret_pct = 100.0 * (und_close - und_open) / abs(und_open)

    pe = prediction_error if isinstance(prediction_error, dict) else {}

    observables: dict[str, Any] = {
        "underlying": str(underlying or "").upper() or None,
        "option_symbol": option_symbol,
        "option_right": right,
        "entry_premium": entry_px,
        "exit_premium": exit_px,
        "premium_return_pct": premium_ret_pct,
        "holding_minutes": hold_minutes,
        "as_of_ist": day,
        "underlying_session": {
            "date": (und_bar or {}).get("date") if und_bar else None,
            "open": und_open,
            "close": und_close,
            "high": und_high,
            "low": und_low,
            "return_pct": und_ret_pct,
            "source": "market/bars durable daily" if und_bar else None,
        },
        "realized_pnl": _f(realized_pnl),
        "prediction_error": {
            "predicted_er": pe.get("predicted_er"),
            "realized_return_pct": pe.get("realized_return_pct"),
            "error_pct": pe.get("error_pct"),
            "direction_match": pe.get("direction_match"),
            "status": pe.get("status"),
        }
        if pe
        else None,
        "mark_source": mark_source,
    }

    missing: list[str] = []
    if und_ret_pct is None:
        missing.append("underlying_session_return")
    if premium_ret_pct is None:
        missing.append("option_premium_path")
    # Greeks / IV not in durable store today — stay explicit unknowns.
    missing.extend(["iv_change", "option_delta", "option_gamma", "news", "sector_rel"])

    evidence_lines = [
        f"underlying={observables['underlying']}",
        f"option={option_symbol}",
        f"right={right}",
        f"entry_premium={entry_px}",
        f"exit_premium={exit_px}",
        f"premium_return_pct={premium_ret_pct}",
        f"underlying_session_return_pct={und_ret_pct}",
        f"holding_minutes={hold_minutes}",
        f"realized_pnl={_f(realized_pnl)}",
        f"mark_source={mark_source}",
        "iv_change=unknown (not in durable store)",
        "delta_gamma=unknown (not in durable store)",
    ]
    if pe.get("direction_match"):
        evidence_lines.append(f"prediction_direction_match={pe.get('direction_match')}")
    if pe.get("error_pct") is not None:
        evidence_lines.append(f"prediction_error_pct={pe.get('error_pct')}")

    return {
        "version": VERSION,
        "kind": "FNO_RT_EVIDENCE",
        "observables": observables,
        "missing_evidence": missing,
        "evidence_lines": evidence_lines,
        "honesty": (
            "Durable underlier daily bars + recorded premiums only. "
            "No invented IV/delta/news. Core may interpret; not a validated lesson."
        ),
    }


def _align_role(
    *,
    right: str | None,
    und_ret_pct: float | None,
    premium_ret_pct: float | None,
) -> str:
    """Path-alignment label for underlying_move vs long option premium."""
    if und_ret_pct is None or abs(und_ret_pct) < _PX_EPS:
        return "unknown"
    r = (right or "").upper()
    und_up = und_ret_pct > 0
    if r == "CE":
        return "helped" if und_up else "hurt"
    if r == "PE":
        return "helped" if not und_up else "hurt"
    # Unknown right — use premium co-movement if available
    if premium_ret_pct is None:
        return "unknown"
    same = (und_ret_pct > 0 and premium_ret_pct > 0) or (
        und_ret_pct < 0 and premium_ret_pct < 0
    )
    return "helped" if same else "hurt"


def evaluate_fno_causal_factors(
    evidence: dict[str, Any] | None,
    *,
    packet: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Map observables → helped/hurt/unknown. Fail-closed; never invent."""
    ev = evidence if isinstance(evidence, dict) else {}
    obs = ev.get("observables") if isinstance(ev.get("observables"), dict) else {}
    und_sess = (
        obs.get("underlying_session")
        if isinstance(obs.get("underlying_session"), dict)
        else {}
    )
    und_ret = _f(und_sess.get("return_pct"))
    prem_ret = _f(obs.get("premium_return_pct"))
    right = str(obs.get("option_right") or "").upper() or None
    pnl = _f(obs.get("realized_pnl"))
    hold = _f(obs.get("holding_minutes"))
    mark_src = str(obs.get("mark_source") or "")
    pe = obs.get("prediction_error") if isinstance(obs.get("prediction_error"), dict) else {}

    factors: list[dict[str, Any]] = []
    missing = list(ev.get("missing_evidence") or [])

    # --- underlying_move (durable daily open→close when present) ---
    if und_ret is None:
        factors.append(
            {
                "factor": "underlying_move",
                "role": "unknown",
                "decide_contrib": None,
                "evidence": None,
                "note": "no durable underlier session bar",
            }
        )
    else:
        role = _align_role(right=right, und_ret_pct=und_ret, premium_ret_pct=prem_ret)
        factors.append(
            {
                "factor": "underlying_move",
                "role": role,
                "decide_contrib": None,
                "evidence": (
                    f"underlier_session_return_pct={und_ret:+.3f} "
                    f"open={und_sess.get('open')} close={und_sess.get('close')} "
                    f"right={right}"
                ),
                "note": (
                    None
                    if role != "unknown"
                    else "underlier move too small to label"
                ),
            }
        )

    # --- option_premium_path (always outcome-side; labels co-movement only) ---
    if prem_ret is None:
        factors.append(
            {
                "factor": "option_premium_path",
                "role": "unknown",
                "decide_contrib": None,
                "evidence": None,
                "note": "entry/exit premium missing",
            }
        )
    else:
        factors.append(
            {
                "factor": "option_premium_path",
                "role": "helped"
                if prem_ret > _PX_EPS
                else ("hurt" if prem_ret < -_PX_EPS else "neutral"),
                "decide_contrib": None,
                "evidence": (
                    f"premium {obs.get('entry_premium')}→{obs.get('exit_premium')} "
                    f"({prem_ret:+.2f}%)"
                ),
                "note": (
                    "Premium path is the measured outcome channel — not an independent cause."
                ),
            }
        )

    # --- entry/exit timing ---
    if hold is None:
        factors.append(
            {
                "factor": "entry_exit_timing",
                "role": "unknown",
                "decide_contrib": None,
                "evidence": None,
                "note": "entry/exit timestamps missing",
            }
        )
    else:
        factors.append(
            {
                "factor": "entry_exit_timing",
                "role": "neutral",
                "decide_contrib": None,
                "evidence": f"holding_minutes={hold:.1f}; exit=session_flat",
                "note": "Session_flat policy — timing is structural, not a causal claim",
            }
        )

    # --- mark quality ---
    if mark_src and "avg_cost" in mark_src.lower():
        factors.append(
            {
                "factor": "mark_quality",
                "role": "hurt",
                "decide_contrib": None,
                "evidence": f"mark_source={mark_src}",
                "note": "Exit used avg-cost fallback — outcome less trustworthy",
            }
        )
    elif mark_src:
        factors.append(
            {
                "factor": "mark_quality",
                "role": "neutral",
                "decide_contrib": None,
                "evidence": f"mark_source={mark_src}",
                "note": None,
            }
        )

    # --- explicit unknowns (must not be filled by LLM invention) ---
    for name, note in (
        ("iv_change", "IV not in durable store for this RT"),
        ("option_greeks", "delta/gamma not recorded at entry/exit"),
        ("news", "no linked headlines on F&O close path"),
        ("sector", "no sector-relative return supplied for underlier"),
    ):
        factors.append(
            {
                "factor": name,
                "role": "unknown",
                "decide_contrib": None,
                "evidence": None,
                "note": note,
            }
        )

    # --- prediction magnitude (observational, not a cause) ---
    if pe.get("status") == "computed" and pe.get("direction_match"):
        factors.append(
            {
                "factor": "prediction_vs_outcome",
                "role": "neutral",
                "decide_contrib": None,
                "evidence": (
                    f"direction_match={pe.get('direction_match')}; "
                    f"error_pct={pe.get('error_pct')}"
                ),
                "note": "Stated E[R] vs realized — measurement, not a market cause",
            }
        )

    helped = [f["factor"] for f in factors if f.get("role") == "helped"]
    hurt = [f["factor"] for f in factors if f.get("role") == "hurt"]
    unknown = [f["factor"] for f in factors if f.get("role") == "unknown"]

    has_und = und_ret is not None
    has_prem = prem_ret is not None
    labeled = bool(helped or hurt)

    if has_und and has_prem and labeled and "underlying_move" in (helped + hurt):
        status = STATUS_EVIDENCE_BACKED
    elif labeled or (has_und and has_prem):
        status = STATUS_PARTIAL
    else:
        status = STATUS_UNKNOWN

    bits: list[str] = []
    if helped:
        bits.append("helped: " + ", ".join(helped[:5]))
    if hurt:
        bits.append("hurt: " + ", ".join(hurt[:5]))
    if unknown:
        bits.append("unknown: " + ", ".join(unknown[:6]))
    if not bits:
        bits.append("no factor labels — insufficient durable evidence")

    # Optional packet passthrough (unused today; reserved)
    _ = packet

    return {
        "version": VERSION,
        "status": status,
        "factors": factors,
        "helped": helped,
        "hurt": hurt,
        "unknown": unknown,
        "missing_evidence": missing,
        "price_change_pct": und_ret,
        "pnl": pnl,
        "narrative": "; ".join(bits),
        "fno_rt_evidence": ev or None,
        "honesty": (
            "F&O path-alignment from durable underlier bars + premiums. "
            "IV/greeks/news stay unknown when absent — Core must not invent them. "
            f"status={status} is not a validated lesson / not L5."
        ),
    }


def evidence_lines_for_core(evidence: dict[str, Any] | None) -> list[str]:
    ev = evidence if isinstance(evidence, dict) else {}
    lines = [str(x) for x in (ev.get("evidence_lines") or []) if x]
    lines.append(
        "ATTRIBUTION_RULE: label only from lines above; "
        "iv_change/delta/gamma/news remain unknown if not listed with values"
    )
    return lines
