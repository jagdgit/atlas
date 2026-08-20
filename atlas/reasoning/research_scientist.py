"""OI-LINT0 Phase 3 — LLM research scientist (advice-only, events only).

The LLM does not place orders. It reviews a bounded packet in four roles
(analyst / skeptic / researcher / teacher) and returns structured JSON.

LLM failure → status UNREVIEWED / LLM_UNAVAILABLE / reschedule.
That is not “belief unchanged.”
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from atlas.llm.provider import ChatMessage

VERSION = "lint0.research_scientist.v1"
STORE_REL = Path("investment") / "research_scientist"
INFLUENCE = "advice_only"
DECISION_ADVICE = "DO_NOT_OVERRIDE_RULE_ENGINE"
DEFAULT_EVENT_PASSES = 3
_IST = ZoneInfo("Asia/Kolkata")
_JSON_RE = re.compile(r"\{[\s\S]*\}")
_log = logging.getLogger("atlas.reasoning.research_scientist")

REVIEWED = "reviewed"
UNREVIEWED = "UNREVIEWED"
LLM_UNAVAILABLE = "LLM_UNAVAILABLE"

_EVENT_ACTIONS = frozenset({"buy", "sell", "reduce"})
_EVENT_TAGS = frozenset(
    {
        "eod_flatten",
        "lab_policy_hold",
        "lab_instrument_rejected",
        "thesis_invalid",
        "identity_quarantined",
        "plc_a_hold",
        "switch_advantage_cleared",
        "switch_exploratory",
    }
)
_SKIP_TAGS = frozenset(
    {
        "mark_only",
        "session_closed",
        "engine_hold",
        "yahoo_cooldown",
        "empty_live_feed",
        "empty_feed",
    }
)

_STANCES = frozenset({"BUY", "WATCH", "AVOID", "INVALID", "ABSENT", "HOLD", "SELL"})

SYSTEM_PROMPT = (
    "You are Atlas's research scientist, not a trading signal. "
    "Perform four roles in one pass: ANALYST (what supports the current view), "
    "SKEPTIC (what could make it wrong), RESEARCHER (what evidence would resolve "
    "uncertainty), TEACHER (what Atlas should remember). "
    "Reply with a single JSON object only. Never invent PE, FCF, prices, or news. "
    "Unknown stays unknown. You must not recommend overriding the rule engine."
)


def _ist_day(now: datetime | None = None) -> str:
    clock = now or datetime.now(timezone.utc)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=timezone.utc)
    return clock.astimezone(_IST).strftime("%Y-%m-%d")


def _safe(s: str) -> str:
    return "".join(c if c.isalnum() or c in "-_^." else "_" for c in (s or "")) or "lab"


def is_scientist_event(
    *,
    action: str,
    strategy_tag: str | None = None,
    contradictions: list[Any] | None = None,
) -> bool:
    a = str(action or "").strip().lower()
    t = str(strategy_tag or "").strip().lower()
    if any(noise in t for noise in _SKIP_TAGS):
        return False
    if a in _EVENT_ACTIONS:
        return True
    if t in _EVENT_TAGS or any(t.startswith(p) for p in ("plc_b_", "plc_a_")):
        return True
    if contradictions:
        return True
    return False


def parse_scientist_json(text: str) -> dict[str, Any] | None:
    raw = (text or "").strip()
    if not raw:
        return None
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        m = _JSON_RE.search(raw)
        if not m:
            return None
        try:
            obj = json.loads(m.group(0))
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            return None


def _clip_list(value: Any, *, limit: int = 8) -> list[str]:
    if isinstance(value, str) and value.strip():
        return [value.strip()[:240]]
    out: list[str] = []
    for item in value or []:
        s = str(item).strip()
        if s:
            out.append(s[:240])
        if len(out) >= limit:
            break
    return out


def normalize_scientist_output(parsed: dict[str, Any] | None) -> dict[str, Any]:
    p = parsed if isinstance(parsed, dict) else {}
    stance = str(p.get("new_stance") or p.get("stance") or "ABSENT").strip().upper()
    if stance not in _STANCES:
        stance = "ABSENT"
    try:
        conf = float(p.get("confidence"))
        if conf > 1.0:
            conf = conf / 100.0
        conf = max(0.0, min(1.0, conf))
    except (TypeError, ValueError):
        conf = None
    changed = bool(p.get("belief_changed"))
    return {
        "belief_changed": changed,
        "new_stance": stance,
        "confidence": conf,
        "important_evidence": _clip_list(p.get("important_evidence")),
        "contradictions": _clip_list(p.get("contradictions")),
        "unknowns": _clip_list(p.get("unknowns")),
        "falsifiers_triggered": _clip_list(p.get("falsifiers_triggered") or p.get("falsifiers")),
        "research_tasks": _clip_list(p.get("research_tasks")),
        "decision_advice": DECISION_ADVICE,
        "er_advice": str(p.get("er_advice") or "").strip()[:400] or None,
        "analyst": str(p.get("analyst") or "")[:500] or None,
        "skeptic": str(p.get("skeptic") or "")[:500] or None,
        "researcher": str(p.get("researcher") or "")[:500] or None,
        "teacher": str(p.get("teacher") or "")[:500] or None,
        "influence": INFLUENCE,
    }


def build_research_packet(
    *,
    symbol: str,
    laboratory_id: str,
    action: str = "",
    strategy_tag: str = "",
    decomposition: dict[str, Any] | None = None,
    prices: dict[str, Any] | None = None,
    indicators: dict[str, Any] | None = None,
    fundamentals: dict[str, Any] | None = None,
    unknowns: list[Any] | None = None,
    thesis: dict[str, Any] | str | None = None,
    falsifiers: list[Any] | None = None,
    position: dict[str, Any] | None = None,
    cash: Any = None,
    challengers: list[dict[str, Any]] | None = None,
    events: dict[str, Any] | None = None,
    relative: dict[str, Any] | None = None,
    expected: dict[str, Any] | None = None,
    ts_ist: str | None = None,
) -> dict[str, Any]:
    """Bounded packet — never the whole Atlas database."""
    fund = fundamentals if isinstance(fundamentals, dict) else {}
    fund_keep = {}
    for k in ("pe", "fcf", "roe", "debt_to_equity", "pb", "roic", "sector"):
        if fund.get(k) is not None:
            fund_keep[k] = fund.get(k)
    unk = [str(x) for x in (unknowns or []) if x][:12]
    if not unk:
        for k in ("fcf", "pe", "promoter_holding", "pb", "debt_to_equity"):
            if k not in fund_keep and k not in {"sector"}:
                unk.append(k)
        unk = unk[:8]
    chal: list[dict[str, Any]] = []
    for row in (challengers or [])[:5]:
        if not isinstance(row, dict):
            continue
        chal.append(
            {
                "symbol": row.get("symbol"),
                "expected_return": row.get("expected_return"),
                "er_completeness": row.get("er_completeness"),
                "role": row.get("role") or "challenger",
            }
        )
    ev = events if isinstance(events, dict) else {}
    if isinstance(ev.get("news"), list) or isinstance(ev.get("policy"), list):
        from atlas.investment.market_events import events_for_packet

        shaped = events_for_packet(
            news=ev.get("news") if isinstance(ev.get("news"), list) else [],
            policy=ev.get("policy") if isinstance(ev.get("policy"), list) else [],
            as_of=ts_ist,
        )
        news = shaped["news"]
        policy = shaped["policy"]
        ev_extra = {
            "news_freshness": shaped.get("news_freshness"),
            "policy_freshness": shaped.get("policy_freshness"),
            "news_status": shaped.get("news_status"),
            "policy_status": shaped.get("policy_status"),
        }
    else:
        news = ev.get("news") if isinstance(ev.get("news"), list) else []
        policy = ev.get("policy") if isinstance(ev.get("policy"), list) else []
        ev_extra = {}
        if not news:
            news = "unknown"
        if not policy:
            policy = "unknown"
    decomp = dict(decomposition or {})
    packet = {
        "version": VERSION,
        "symbol": str(symbol or "").strip().upper(),
        "laboratory": str(laboratory_id or "").strip(),
        "ts_ist": ts_ist or _ist_day(),
        "action": str(action or "").strip().lower(),
        "strategy_tag": str(strategy_tag or "").strip(),
        "price": {
            "mark": (prices or {}).get("mark") if isinstance(prices, dict) else None,
            "fill": (prices or {}).get("fill_price") if isinstance(prices, dict) else None,
        },
        "technical": {
            "rsi": (indicators or {}).get("rsi") or (indicators or {}).get("rsi14"),
            "sma_fast": (indicators or {}).get("sma_fast"),
            "sma_slow": (indicators or {}).get("sma_slow"),
            "signal": decomp.get("technical_signal"),
        },
        "relative": dict(relative) if isinstance(relative, dict) else {},
        "fundamentals": fund_keep,
        "unknowns": unk,
        "thesis": thesis if thesis is not None else {
            "stance": decomp.get("fundamental_thesis"),
            "identity": decomp.get("identity"),
        },
        "falsifiers": [str(x)[:160] for x in (falsifiers or []) if x][:6],
        "portfolio": {
            "position": position if isinstance(position, dict) else None,
            "cash": cash,
        },
        "challengers": chal,
        "events": {
            "news": news if news != "unknown" else "unknown",
            "policy": policy if policy != "unknown" else "unknown",
            **ev_extra,
        },
        "expected": {
            "expected_return": (expected or {}).get("expected_return") if isinstance(expected, dict) else None,
            "er_completeness": (expected or {}).get("er_completeness") if isinstance(expected, dict) else None,
            "er_basis": (expected or {}).get("er_basis") if isinstance(expected, dict) else None,
        },
        "decomposition": {
            k: decomp.get(k)
            for k in (
                "technical_signal",
                "fundamental_thesis",
                "identity",
                "lab_policy",
                "final_decision",
                "contradictions",
            )
            if decomp
        },
        "question": (
            "Should the existing thesis change? Is the technical signal consistent "
            "with the thesis? What evidence is missing? What research should Atlas "
            "perform? Did E[R] assessment change? Do not override the rule engine."
        ),
    }
    return packet


def scientist_prompt(packet: dict[str, Any]) -> str:
    schema = {
        "belief_changed": False,
        "new_stance": "WATCH",
        "confidence": 0.0,
        "important_evidence": [],
        "contradictions": [],
        "unknowns": [],
        "falsifiers_triggered": [],
        "research_tasks": [],
        "decision_advice": DECISION_ADVICE,
        "er_advice": None,
        "analyst": "",
        "skeptic": "",
        "researcher": "",
        "teacher": "",
    }
    return json.dumps(
        {
            "roles": ["analyst", "skeptic", "researcher", "teacher"],
            "packet": packet,
            "return_schema": schema,
            "rules": [
                "JSON only",
                "decision_advice must be DO_NOT_OVERRIDE_RULE_ENGINE",
                "do not invent fundamentals or news",
                "belief_changed true only with cited packet evidence",
            ],
        },
        default=str,
    )


def chat_with_retry(
    llm: Any,
    messages: list[ChatMessage],
    *,
    attempts: int = 2,
) -> tuple[str | None, str | None]:
    """Return (text, error). Retry once on timeout/failure."""
    last_err: str | None = None
    n = max(1, int(attempts))
    for i in range(n):
        try:
            client = llm.for_role("researcher") if hasattr(llm, "for_role") else llm
            resp = client.chat(messages)
            text = getattr(resp, "text", None) or getattr(resp, "content", None) or str(resp)
            if text and str(text).strip():
                return str(text), None
            last_err = "empty_response"
        except Exception as exc:  # noqa: BLE001
            last_err = f"{type(exc).__name__}: {exc}"[:240]
            _log.debug("research scientist LLM attempt %s failed: %s", i + 1, last_err)
    return None, last_err or LLM_UNAVAILABLE


def _budget_path(data_dir: str | Path, laboratory_id: str, ist_day: str) -> Path:
    return (
        Path(data_dir)
        / STORE_REL
        / _safe(laboratory_id)
        / f"{ist_day}.budget.json"
    )


def _load_budget(data_dir: str | Path, laboratory_id: str, ist_day: str) -> dict[str, Any]:
    path = _budget_path(data_dir, laboratory_id, ist_day)
    if not path.is_file():
        return {"version": VERSION, "day": ist_day, "used": 0, "max": DEFAULT_EVENT_PASSES}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else {"used": 0, "max": DEFAULT_EVENT_PASSES}
    except (OSError, json.JSONDecodeError):
        return {"used": 0, "max": DEFAULT_EVENT_PASSES}


def _save_budget(data_dir: str | Path, laboratory_id: str, ist_day: str, doc: dict[str, Any]) -> None:
    path = _budget_path(data_dir, laboratory_id, ist_day)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    except OSError:
        _log.debug("scientist budget write failed", exc_info=True)


def _queue_path(data_dir: str | Path, laboratory_id: str) -> Path:
    return Path(data_dir) / STORE_REL / _safe(laboratory_id) / "reschedule.jsonl"


def enqueue_unreviewed(
    data_dir: str | Path | None,
    *,
    laboratory_id: str,
    packet: dict[str, Any],
    reason: str,
) -> None:
    if not data_dir:
        return
    path = _queue_path(data_dir, laboratory_id)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        rec = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "reason": reason,
            "status": UNREVIEWED,
            "symbol": packet.get("symbol"),
            "packet": packet,
        }
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, default=str) + "\n")
    except OSError:
        _log.debug("scientist queue write failed", exc_info=True)


def _unreviewed_result(
    *,
    reason: str,
    packet: dict[str, Any],
    reschedule: bool = True,
) -> dict[str, Any]:
    empty = normalize_scientist_output({})
    empty["belief_changed"] = False
    return {
        "version": VERSION,
        "status": UNREVIEWED,
        "reason": reason,
        "reschedule": bool(reschedule),
        "belief_changed": False,
        "output": empty,
        "packet": packet,
        "influence": INFLUENCE,
        "llm": False,
    }


def run_research_scientist(
    *,
    llm: Any | None,
    packet: dict[str, Any] | None = None,
    data_dir: str | Path | None = None,
    max_passes: int = DEFAULT_EVENT_PASSES,
    consume_budget: bool = True,
    enqueue_on_fail: bool = True,
    **packet_kwargs: Any,
) -> dict[str, Any]:
    """Run one event-triggered scientist pass. Never returns an order."""
    pkt = packet if isinstance(packet, dict) else build_research_packet(**packet_kwargs)
    action = str(pkt.get("action") or packet_kwargs.get("action") or "")
    tag = str(pkt.get("strategy_tag") or packet_kwargs.get("strategy_tag") or "")
    decomp = pkt.get("decomposition") if isinstance(pkt.get("decomposition"), dict) else {}
    if not is_scientist_event(
        action=action,
        strategy_tag=tag,
        contradictions=list(decomp.get("contradictions") or []),
    ):
        return {
            "version": VERSION,
            "status": "skipped",
            "reason": "not_an_event",
            "reschedule": False,
            "belief_changed": False,
            "output": None,
            "packet": pkt,
            "influence": INFLUENCE,
            "llm": False,
        }

    lab = str(pkt.get("laboratory") or packet_kwargs.get("laboratory_id") or "unknown")
    day = str(pkt.get("ts_ist") or _ist_day())
    if data_dir and consume_budget:
        bud = _load_budget(data_dir, lab, day)
        used = int(bud.get("used") or 0)
        cap = int(bud.get("max") or max_passes)
        if used >= cap:
            out = _unreviewed_result(reason="cognitive_budget_exhausted", packet=pkt)
            if enqueue_on_fail:
                enqueue_unreviewed(data_dir, laboratory_id=lab, packet=pkt, reason=out["reason"])
            return out

    if llm is None:
        out = _unreviewed_result(reason=LLM_UNAVAILABLE, packet=pkt)
        if enqueue_on_fail:
            enqueue_unreviewed(data_dir, laboratory_id=lab, packet=pkt, reason=out["reason"])
        return out

    messages = [
        ChatMessage(role="system", content=SYSTEM_PROMPT),
        ChatMessage(role="user", content=scientist_prompt(pkt)),
    ]
    text, err = chat_with_retry(llm, messages, attempts=2)
    if not text:
        out = _unreviewed_result(reason=f"{LLM_UNAVAILABLE}:{err}"[:200] if err else LLM_UNAVAILABLE, packet=pkt)
        if enqueue_on_fail:
            enqueue_unreviewed(data_dir, laboratory_id=lab, packet=pkt, reason=out["reason"])
        return out

    parsed = parse_scientist_json(text)
    if not parsed:
        out = _unreviewed_result(reason="LLM_PARSE_FAILED", packet=pkt)
        if enqueue_on_fail:
            enqueue_unreviewed(data_dir, laboratory_id=lab, packet=pkt, reason=out["reason"])
        return out

    if data_dir and consume_budget:
        bud = _load_budget(data_dir, lab, day)
        bud["used"] = int(bud.get("used") or 0) + 1
        bud["max"] = int(bud.get("max") or max_passes)
        bud["day"] = day
        _save_budget(data_dir, lab, day, bud)

    output = normalize_scientist_output(parsed)
    return {
        "version": VERSION,
        "status": REVIEWED,
        "reason": "ok",
        "reschedule": False,
        "belief_changed": bool(output.get("belief_changed")),
        "output": output,
        "packet": pkt,
        "influence": INFLUENCE,
        "llm": True,
    }


def drain_scientist_queue(
    data_dir: str | Path | None,
    *,
    laboratory_id: str,
    llm: Any | None,
    max_n: int = 3,
) -> dict[str, Any]:
    """Retry UNREVIEWED packets. Still advice-only."""
    if not data_dir:
        return {"done": 0, "pending": 0, "skipped": 0}
    path = _queue_path(data_dir, laboratory_id)
    if not path.is_file():
        return {"done": 0, "pending": 0, "skipped": 0}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {"done": 0, "pending": 0, "skipped": 0}
    remaining: list[str] = []
    done = 0
    skipped = 0
    for line in lines:
        if not line.strip():
            continue
        if done >= max_n:
            remaining.append(line)
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            skipped += 1
            continue
        pkt = rec.get("packet") if isinstance(rec, dict) else None
        if not isinstance(pkt, dict):
            skipped += 1
            continue
        if not pkt.get("question"):
            pkt = build_research_packet(
                symbol=str(pkt.get("symbol") or ""),
                laboratory_id=str(pkt.get("laboratory") or laboratory_id),
                action=str(pkt.get("action") or ""),
                strategy_tag=str(pkt.get("strategy_tag") or ""),
                decomposition=pkt.get("decomposition") if isinstance(pkt.get("decomposition"), dict) else None,
                prices=pkt.get("price") if isinstance(pkt.get("price"), dict) else None,
                fundamentals=pkt.get("fundamentals") if isinstance(pkt.get("fundamentals"), dict) else None,
                expected=pkt.get("expected") if isinstance(pkt.get("expected"), dict) else None,
                ts_ist=str(pkt.get("ts_ist") or "") or None,
            )
        out = run_research_scientist(
            llm=llm,
            packet=pkt,
            data_dir=data_dir,
            consume_budget=True,
            enqueue_on_fail=False,
        )
        if out.get("status") == REVIEWED:
            done += 1
        else:
            remaining.append(line)
    try:
        path.write_text("\n".join(remaining) + ("\n" if remaining else ""), encoding="utf-8")
    except OSError:
        pass
    return {"done": done, "pending": len(remaining), "skipped": skipped}
