"""Decision chain for trade emails: why this fill happened, joined from stored records.

Reads trade lineage (keyed by fill trade id), the decision packets in
``investment/decisions/by_id`` and the F&O entry prediction. Prints only what
was recorded at decide time; anything missing is said to be missing.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

_IST = ZoneInfo("Asia/Kolkata")
LOOKBACK_DAYS = 7

EXIT_REASON_TEXT = {
    "premium_stop": "premium stop hit (option premium fell to the stop level)",
    "premium_target": "premium target hit",
    "underlier_reversal": "underlier trend turned against the option",
    "fno_lab_v1_experiment_close": "session close-out (options are never held overnight)",
    "eod_flatten": "intraday end-of-day flatten",
}


def _short(value: Any) -> str:
    return str(value)[:8] if value else "—"


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        ts = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def _hm(value: Any) -> str:
    ts = _parse_ts(value)
    return ts.astimezone(_IST).strftime("%Y-%m-%d %H:%M IST") if ts else "?"


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        doc = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
    except (OSError, json.JSONDecodeError):
        return None
    return doc if isinstance(doc, dict) else None


def _lineage_rows(data_dir: Path, lab: str, symbol: str, upto_day: str) -> list[dict[str, Any]]:
    root = data_dir / "investment" / "trade_lineage" / lab
    end = datetime.fromisoformat(upto_day).date()
    rows: list[dict[str, Any]] = []
    for i in range(LOOKBACK_DAYS - 1, -1, -1):
        path = root / f"{(end - timedelta(days=i)).isoformat()}.jsonl"
        if not path.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if str(row.get("symbol") or "") == symbol:
                rows.append(row)
    return rows


def _entry_buy_for_sell(rows: list[dict[str, Any]], sell: dict[str, Any]) -> dict[str, Any] | None:
    open_lots: list[dict[str, Any]] = []
    for row in rows:
        if row.get("lineage_id") == sell.get("lineage_id"):
            break
        side = str(row.get("side") or "").lower()
        if side == "buy":
            open_lots.append(row)
        elif side == "sell" and open_lots:
            open_lots.pop()
    return open_lots[-1] if open_lots else None


def _packet(data_dir: Path, decision_id: Any) -> dict[str, Any] | None:
    if not decision_id:
        return None
    return _read_json(data_dir / "investment" / "decisions" / "by_id" / f"{decision_id}.json")


def _prediction(data_dir: Path, lineage: dict[str, Any], packet: dict[str, Any] | None) -> dict[str, Any]:
    pid = lineage.get("prediction_id")
    if pid:
        try:
            from atlas.investment import fno_lab_v1

            doc = fno_lab_v1.load_entry_prediction(data_dir, prediction_id=str(pid))
            if doc:
                return doc
        except Exception:  # noqa: BLE001
            pass
    expected = (packet or {}).get("expected")
    return dict(expected) if isinstance(expected, dict) else {}


def _pct(x: Any) -> str:
    try:
        return f"{float(x) * 100:+.1f}%"
    except (TypeError, ValueError):
        return "?"


def _prediction_lines(pred: dict[str, Any]) -> list[str]:
    if not pred.get("expected_return") and not pred.get("thesis"):
        return ["  Prediction: none stated at entry"]
    out = [
        "  Prediction at entry: "
        + f"E[R] {_pct(pred.get('expected_return'))}"
        + (f", p={float(pred['predicted_probability']):.2f}" if pred.get("predicted_probability") is not None else "")
        + f", horizon {pred.get('prediction_horizon') or pred.get('holding_horizon') or '?'}"
        + f", model {pred.get('er_model') or '?'}"
        + (" (uncalibrated)" if "control_signal" in str(pred.get("er_model") or "") else "")
    ]
    if pred.get("thesis"):
        out.append(f"  Thesis: {pred['thesis']}")
    for ev in list(pred.get("key_evidence") or [])[:6]:
        out.append(f"    · {ev}")
    return out


def _learning_line(lab: str, sell: dict[str, Any]) -> str | None:
    timing = sell.get("exit_timing")
    if not timing and lab == "india_fno_learner":
        from atlas.investment import fno_lab_v1

        timing = fno_lab_v1.exit_learning_eligibility(_parse_ts(sell.get("recorded_at")))["exit_timing"]
    if timing == "after_close":
        return "  Learning: NOT eligible (exit after the NSE close — last print, not a tradeable price); excluded from learning"
    if timing == "in_session":
        return "  Learning: eligible (in-session exit)"
    return None


def build_decision_chain(
    data_dir: str | Path | None,
    *,
    laboratory_id: str,
    symbol: str,
    side: str,
    trade_id: str | None,
    now: datetime | None = None,
) -> list[str]:
    """Lines for the 'Decision chain' block of a fill email. Never raises."""
    try:
        return _build(Path(data_dir), laboratory_id, symbol, side, trade_id, now) if data_dir else []
    except Exception as exc:  # noqa: BLE001
        return [f"  (decision chain unavailable: {type(exc).__name__})"]


def _build(
    data_dir: Path, lab: str, symbol: str, side: str, trade_id: str | None, now: datetime | None
) -> list[str]:
    clock = now or datetime.now(timezone.utc)
    day = clock.astimezone(_IST).date().isoformat()
    rows = _lineage_rows(data_dir, lab, symbol, day)
    me = next((r for r in reversed(rows) if trade_id and r.get("fill_trade_id") == trade_id), None)
    if me is None:
        return ["  Not recorded: no trade-lineage row for this fill (decision chain cannot be shown)."]
    intent = me.get("order_intent") or {}
    lines: list[str] = []
    if str(me.get("side") or side).lower() == "buy":
        lines.append(
            f"  Control rule: {intent.get('engine_action') or '?'} (decision {_short(intent.get('engine_decision_id'))})"
        )
        if intent.get("overlay_used"):
            lines.append(
                f"  Overlay: {intent.get('rationale_text') or '?'} (decision {_short(me.get('overlay_decision_id'))})"
            )
        entry_id = me.get("entry_decision_id") or me.get("overlay_decision_id")
        packet = _packet(data_dir, entry_id)
        reasons = list((packet or {}).get("reasons_for") or [])
        if reasons:
            lines.append(f"  Reasons for: {', '.join(str(r) for r in reasons[:5])}")
        against = list((packet or {}).get("reasons_against") or [])
        if against:
            lines.append(f"  Reasons against: {', '.join(str(r) for r in against[:5])}")
        lines.extend(_prediction_lines(_prediction(data_dir, me, packet)))
        lines.append(f"  Prediction id: {me.get('prediction_id') or 'not recorded'}")
    else:
        code = str(me.get("exit_reason_code") or me.get("instrument_path") or "sell")
        lines.append(f"  Exit reason: {code} — {EXIT_REASON_TEXT.get(code, 'see exit decision')}")
        lines.append(f"  Exit decision: {_short(me.get('exit_decision_id'))}")
        buy = _entry_buy_for_sell(rows, me)
        if buy is None:
            lines.append("  Entry: not found in the last 7 days of lineage")
        else:
            entry_id = me.get("entry_decision_id") or buy.get("entry_decision_id") or buy.get("overlay_decision_id")
            linked = "linked on the sell" if me.get("entry_decision_id") else "matched by symbol, sell carried no entry link"
            lines.append(
                f"  Entry: bought {buy.get('quantity')} @ {buy.get('price')} at {_hm(buy.get('recorded_at'))}"
                f" (decision {_short(entry_id)}; {linked})"
            )
            held = (_parse_ts(me.get("recorded_at")) or clock) - (_parse_ts(buy.get("recorded_at")) or clock)
            lines.append(f"  Held: {int(held.total_seconds() // 60)} min")
            packet = _packet(data_dir, entry_id)
            pred = _prediction(data_dir, buy, packet)
            lines.extend(_prediction_lines(pred))
            try:
                actual = float(me.get("price")) / float(buy.get("price")) - 1.0
            except (TypeError, ValueError, ZeroDivisionError):
                actual = None
            if actual is not None:
                exp = pred.get("expected_return")
                verdict = ""
                if exp is not None:
                    right = (actual > 0) == (float(exp) > 0)
                    verdict = f" vs predicted {_pct(exp)} → direction {'RIGHT' if right else 'WRONG'}, error {_pct(actual - float(exp))}"
                lines.append(f"  Outcome: price return {_pct(actual)}{verdict}")
        learning = _learning_line(lab, me)
        if learning:
            lines.append(learning)
    if me.get("lineage_incomplete"):
        lines.append(f"  Lineage incomplete: {', '.join(me.get('integrity_issues') or ['unknown'])}")
    return lines
