"""NOW #11 — Capital Scale Laboratory (virtual ₹1L…₹2Cr).

Counterfactual sizing / concentration analysis on top of Next-₹1.
**Never** mutates live paper capital, starting_cash, or broker state.
Real-money increase remains forbidden until operator unlock after Scale Lab.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

VERSION = "now.capital_scale.v1"
STORE_REL = Path("investment") / "capital_scale"
_IST = ZoneInfo("Asia/Kolkata")
_log = logging.getLogger("atlas.investment.capital_scale_lab")

# ₹1L … ₹2Cr virtual bands (locked NOW roadmap)
DEFAULT_BANDS_INR: tuple[int, ...] = (
    100_000,  # 1L
    500_000,  # 5L
    1_000_000,  # 10L
    2_500_000,  # 25L
    5_000_000,  # 50L
    10_000_000,  # 1Cr
    20_000_000,  # 2Cr
)

DEFAULT_DEPLOY_FRACTION = 0.10  # first Next-₹1 notional as 10% of band
DEFAULT_MAX_NAME_PCT = 0.25
MIN_ER_COMPLETENESS_FOR_LARGE = 0.45  # honesty gate at ≥10L


def ist_today() -> str:
    return datetime.now(_IST).strftime("%Y-%m-%d")


def _f(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def format_inr(amount: float | int) -> str:
    n = float(amount)
    if n >= 10_000_000:
        return f"₹{n / 10_000_000:.2f}Cr"
    if n >= 100_000:
        return f"₹{n / 100_000:.2f}L"
    return f"₹{n:,.0f}"


def analyze_scale_band(
    *,
    band_inr: float,
    destination: str | None,
    destination_action: str | None = None,
    destination_er: float | None = None,
    destination_er_completeness: float | None = None,
    deploy_fraction: float = DEFAULT_DEPLOY_FRACTION,
    max_name_pct: float = DEFAULT_MAX_NAME_PCT,
    live_equity: float | None = None,
) -> dict[str, Any]:
    """Counterfactual band analysis — does not place orders or change capital."""
    band = max(0.0, float(band_inr))
    frac = max(0.0, min(1.0, float(deploy_fraction)))
    deploy = round(band * frac, 2)
    dest = str(destination or "CASH").upper()
    action = str(destination_action or ("HOLD_CASH" if dest == "CASH" else "DEPLOY"))
    comp = _f(destination_er_completeness)
    warnings: list[str] = []
    gates: list[str] = []

    if dest != "CASH" and frac > float(max_name_pct):
        warnings.append(
            f"Deploy fraction {frac:.0%} exceeds max single-name {float(max_name_pct):.0%} "
            f"at {format_inr(band)}"
        )
    if dest != "CASH" and band >= 1_000_000:
        if comp is None:
            warnings.append("E[R] completeness unknown at ≥₹10L — treat as fragile")
            gates.append("completeness_unknown")
        elif comp < MIN_ER_COMPLETENESS_FOR_LARGE:
            warnings.append(
                f"E[R] completeness {comp:.2f} < {MIN_ER_COMPLETENESS_FOR_LARGE} "
                f"at {format_inr(band)} — Scale Lab would HOLD densify before size-up"
            )
            gates.append("completeness_thin")
    if live_equity is not None and band > float(live_equity) * 5:
        warnings.append(
            f"Band {format_inr(band)} ≫ live book {format_inr(live_equity)} — "
            "purely counterfactual"
        )

    # Verdict: still follow Next-₹1 destination, but flag when scale would block size
    if action == "HOLD_CASH" or dest == "CASH":
        verdict = "HOLD_CASH"
        note = f"At {format_inr(band)}, Next-₹1 stays cash (no deploy target)."
    elif gates:
        verdict = "SCALE_HOLD"
        note = (
            f"At {format_inr(band)}, destination remains {dest} conceptually, "
            f"but Scale Lab gates size-up ({', '.join(gates)})."
        )
    else:
        verdict = "SCALE_OK"
        note = (
            f"At {format_inr(band)}, virtual Next-₹1 still → {dest} "
            f"(~{format_inr(deploy)} notional @ {frac:.0%} band)."
        )

    return {
        "band_inr": band,
        "band_label": format_inr(band),
        "destination": dest,
        "destination_action": action,
        "destination_er": destination_er,
        "destination_er_completeness": comp,
        "deploy_fraction": frac,
        "deploy_notional_inr": deploy,
        "verdict": verdict,
        "note": note,
        "warnings": warnings[:6],
        "gates": gates,
        "mutates_live_capital": False,
        "real_capital_increase": False,
    }


def build_capital_scale_lab(
    *,
    next_rupee: dict[str, Any] | None,
    laboratory_id: str = "india_equity_learner",
    bands_inr: tuple[int, ...] | list[int] | None = None,
    live_cash: float | None = None,
    live_equity: float | None = None,
    as_of_ist: str | None = None,
    deploy_fraction: float = DEFAULT_DEPLOY_FRACTION,
    max_name_pct: float = DEFAULT_MAX_NAME_PCT,
) -> dict[str, Any]:
    """Full virtual Scale Lab packet from durable Next-₹1 (advice / counterfactual)."""
    nr = next_rupee if isinstance(next_rupee, dict) else {}
    day = (as_of_ist or nr.get("as_of_ist") or ist_today()).strip()
    bands = tuple(bands_inr) if bands_inr else DEFAULT_BANDS_INR
    dest = nr.get("destination")
    scenarios = [
        analyze_scale_band(
            band_inr=b,
            destination=str(dest) if dest else "CASH",
            destination_action=nr.get("destination_action"),
            destination_er=_f(nr.get("destination_er")),
            destination_er_completeness=_f(nr.get("destination_er_completeness")),
            deploy_fraction=deploy_fraction,
            max_name_pct=max_name_pct,
            live_equity=live_equity,
        )
        for b in bands
    ]
    ok_n = sum(1 for s in scenarios if s.get("verdict") == "SCALE_OK")
    hold_n = sum(1 for s in scenarios if s.get("verdict") == "SCALE_HOLD")
    cash_n = sum(1 for s in scenarios if s.get("verdict") == "HOLD_CASH")
    first_gate = next((s for s in scenarios if s.get("verdict") == "SCALE_HOLD"), None)
    operator = (
        f"Capital Scale Lab (virtual): Next-₹1 → {dest or 'CASH'} across "
        f"{format_inr(bands[0])}…{format_inr(bands[-1])}. "
        f"SCALE_OK={ok_n} · SCALE_HOLD={hold_n} · CASH={cash_n}."
    )
    if first_gate:
        operator += f" First size gate at {first_gate.get('band_label')}: {first_gate.get('note')}"
    operator += " Live paper capital unchanged."

    return {
        "version": VERSION,
        "kind": "CAPITAL_SCALE_LAB",
        "laboratory_id": laboratory_id,
        "as_of_ist": day,
        "recorded_at": datetime.now(_IST).isoformat(),
        "next_rupee_destination": dest,
        "next_rupee_action": nr.get("destination_action"),
        "next_rupee_answer": (nr.get("operator_answer") or "")[:400],
        "live_cash": live_cash,
        "live_equity": live_equity,
        "bands_inr": list(bands),
        "scenarios": scenarios,
        "summary": {
            "scale_ok": ok_n,
            "scale_hold": hold_n,
            "hold_cash": cash_n,
            "first_gate_band": (first_gate or {}).get("band_label"),
        },
        "operator_answer": operator[:700],
        "mutates_live_capital": False,
        "real_capital_increase": False,
        "never_orders": True,
        "advice_only": True,
        "honesty": (
            "Capital Scale Lab is virtual/counterfactual only. "
            "It does not increase live paper or real capital, place orders, "
            "or change starting_cash. Next-₹1 remains the economic center."
        ),
    }


def store_dir(data_dir: str | Path, laboratory_id: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in laboratory_id)[:80]
    return Path(data_dir) / STORE_REL / (safe or "lab")


def persist_capital_scale(
    data_dir: str | Path | None,
    doc: dict[str, Any],
) -> dict[str, Any] | None:
    if not data_dir or not isinstance(doc, dict):
        return None
    lab = str(doc.get("laboratory_id") or "lab")
    day = str(doc.get("as_of_ist") or ist_today())
    root = store_dir(data_dir, lab)
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{day}.json"
    latest = root / "_latest.json"
    try:
        text = json.dumps(doc, indent=2, default=str) + "\n"
        path.write_text(text, encoding="utf-8")
        latest.write_text(text, encoding="utf-8")
    except OSError:
        _log.debug("capital_scale persist failed", exc_info=True)
        return None
    out = dict(doc)
    out["path"] = str(path)
    return out


def load_capital_scale(
    data_dir: str | Path | None,
    laboratory_id: str,
    *,
    as_of_ist: str | None = None,
) -> dict[str, Any] | None:
    if not data_dir:
        return None
    root = store_dir(data_dir, laboratory_id)
    path = root / f"{(as_of_ist or ist_today()).strip()}.json"
    if not path.is_file():
        path = root / "_latest.json"
    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else None
    except Exception:  # noqa: BLE001
        return None


def build_and_persist_capital_scale(
    data_dir: str | Path | None,
    *,
    laboratory_id: str,
    next_rupee: dict[str, Any] | None = None,
    live_cash: float | None = None,
    live_equity: float | None = None,
    bands_inr: tuple[int, ...] | list[int] | None = None,
) -> dict[str, Any]:
    nr = next_rupee
    if nr is None and data_dir:
        try:
            from atlas.investment.next_rupee import load_next_rupee

            nr = load_next_rupee(data_dir, laboratory_id)
        except Exception:  # noqa: BLE001
            nr = None
    doc = build_capital_scale_lab(
        next_rupee=nr,
        laboratory_id=laboratory_id,
        bands_inr=bands_inr,
        live_cash=live_cash,
        live_equity=live_equity,
    )
    if data_dir:
        persisted = persist_capital_scale(data_dir, doc)
        if persisted:
            return persisted
    return doc


def format_capital_scale_evening_lines(
    doc: dict[str, Any] | None,
    *,
    limit: int = 5,
) -> list[str]:
    if not isinstance(doc, dict) or not doc.get("scenarios"):
        return [
            "",
            "── Capital Scale Lab (virtual ₹1L…₹2Cr) ──",
            "  (unavailable — no scale packet today)",
        ]
    lines = [
        "",
        "── Capital Scale Lab (virtual — live capital unchanged) ──",
        f"  {doc.get('operator_answer')}",
    ]
    for s in (doc.get("scenarios") or [])[: max(1, int(limit))]:
        if not isinstance(s, dict):
            continue
        warn = f" · {s['warnings'][0]}" if s.get("warnings") else ""
        lines.append(
            f"  · {s.get('band_label')}: {s.get('verdict')} → {s.get('destination')} "
            f"notional={format_inr(s.get('deploy_notional_inr') or 0)}{warn}"
        )
    if len(doc.get("scenarios") or []) > limit:
        lines.append(f"  · … +{len(doc['scenarios']) - limit} more bands")
    lines.append(f"  Honesty: {doc.get('honesty')}")
    return lines


def detect_capital_scale_query(message: str) -> bool:
    low = (message or "").strip().lower()
    if not low:
        return False
    needles = (
        "capital scale",
        "scale lab",
        "at 1 crore",
        "at 1cr",
        "at ₹1",
        "at 2 crore",
        "virtual capital",
        "if we had 1l",
        "if we had ₹1",
        "scale to 1",
        "what happens at 10l",
        "what happens at 1cr",
    )
    return any(n in low for n in needles)


def answer_capital_scale_chat(
    message: str,
    *,
    data_dir: str | Path | None = None,
    laboratory_id: str = "india_equity_learner",
) -> dict[str, Any] | None:
    if not detect_capital_scale_query(message):
        return None
    doc = load_capital_scale(data_dir, laboratory_id) if data_dir else None
    if not isinstance(doc, dict):
        return {
            "ok": True,
            "kind": "capital_scale",
            "answer": (
                "Capital Scale Lab packet not persisted yet. After a paper tick, "
                "Atlas reports virtual ₹1L…₹2Cr scenarios on Next-₹1 without "
                "changing live capital. Advice-only — no orders."
            ),
            "never_orders": True,
            "mutates_live_capital": False,
            "real_capital_increase": False,
        }
    lines = format_capital_scale_evening_lines(doc, limit=7)
    # Drop leading blank from evening formatter for chat
    while lines and not lines[0].strip():
        lines = lines[1:]
    return {
        "ok": True,
        "kind": "capital_scale",
        "answer": "\n".join(lines),
        "capital_scale": {
            "destination": doc.get("next_rupee_destination"),
            "summary": doc.get("summary"),
            "as_of_ist": doc.get("as_of_ist"),
        },
        "never_orders": True,
        "mutates_live_capital": False,
        "real_capital_increase": False,
        "advice_only": True,
    }
