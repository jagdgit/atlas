"""LLM research for the cognitive loop: post-trade reviews and proposed questions.

The LLM proposes, the evidence decides. Two jobs, both advice-only:

* **Post-trade review** (R1): one closed, learning-eligible round trip at a time —
  what happened, what drove it, what was luck, what data was missing, and
  optionally one testable idea.
* **Hypothesis proposals** (R2): given a per-feature table of closed episodes and
  the questions already asked, propose up to three splits worth testing, each
  with a mechanism and a falsifier.

Nothing here admits, tests, or promotes. Proposals land in an inbox; the nightly
cycle validates each against the data and sends survivors through the same
admission → fresh-sample test → ladder as detector-found patterns. The LLM never
sees an order path and its output never changes strategy or sizing.

Runs off-hours only (outside 09:00–15:45 IST on weekdays), one LLM call per
invocation, with a daily call budget.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

VERSION = "cognitive.llm_research.v1"
STORE_REL = Path("investment") / "cognitive" / "llm_research"
INFLUENCE = "advice_only"
SOURCE_LLM = "llm_proposed"

MAX_CALLS_PER_DAY = 8
MAX_PROPOSALS = 3
PROPOSAL_LOOKBACK_DAYS = 3
NUM_PREDICT = 500
SESSION_START_MIN = 9 * 60
SESSION_END_MIN = 15 * 60 + 45

_IST = ZoneInfo("Asia/Kolkata")
_log = logging.getLogger("atlas.investment.cognitive.llm_research")

_SHORT = {"type": "string", "maxLength": 240}
_SHORT_LIST = {"type": "array", "items": _SHORT, "maxItems": 3}

REVIEW_SYSTEM = (
    "You are Atlas's trade reviewer for a paper options lab. You review one closed "
    "round trip using only the facts in the packet. Separate what the signal got "
    "right from luck. Never invent prices, news, or Greeks that are not in the packet; "
    "name missing data instead. You do not place or recommend orders."
)

PROPOSAL_SYSTEM = (
    "You are Atlas's research scientist. You propose questions, not conclusions. "
    "Each proposal names one decide-time feature and two of its groups whose "
    "direction-match rates may genuinely differ, with a market mechanism that would "
    "explain it and what result would prove it wrong. Every proposal will be tested "
    "only on future trades; a small sample now is not evidence either way. Prefer "
    "questions not already asked. You do not place or recommend orders."
)


def _now_ist(now: datetime | None = None) -> datetime:
    clock = now or datetime.now(timezone.utc)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=timezone.utc)
    return clock.astimezone(_IST)


def off_hours(now: datetime | None = None) -> bool:
    ist = _now_ist(now)
    if ist.weekday() >= 5:
        return True
    minutes = ist.hour * 60 + ist.minute
    return not (SESSION_START_MIN <= minutes < SESSION_END_MIN)


def _root(data_dir: str | Path, laboratory_id: str) -> Path:
    return Path(data_dir) / STORE_REL / str(laboratory_id)


def _append(path: Path, row: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    except OSError:
        _log.debug("llm research write failed: %s", path, exc_info=True)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


# --- budget -----------------------------------------------------------------


def _budget_path(data_dir: str | Path, laboratory_id: str, day: str) -> Path:
    return _root(data_dir, laboratory_id) / "budget" / f"{day}.json"


def _calls_today(data_dir: str | Path, laboratory_id: str, day: str) -> int:
    path = _budget_path(data_dir, laboratory_id, day)
    try:
        return int(json.loads(path.read_text(encoding="utf-8")).get("calls") or 0)
    except (OSError, ValueError, AttributeError):
        return 0


def _spend(data_dir: str | Path, laboratory_id: str, day: str) -> None:
    path = _budget_path(data_dir, laboratory_id, day)
    doc = {"version": VERSION, "day": day, "calls": _calls_today(data_dir, laboratory_id, day) + 1,
           "cap": MAX_CALLS_PER_DAY}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc) + "\n", encoding="utf-8")
    except OSError:
        _log.debug("llm research budget write failed", exc_info=True)


def _chat_json(llm: Any, system: str, user: str, schema: dict[str, Any], purpose: str) -> tuple[dict[str, Any] | None, str | None]:
    from atlas.llm.provider import ChatMessage

    try:
        client = llm.for_role("researcher") if hasattr(llm, "for_role") else llm
        resp = client.chat(
            [ChatMessage(role="system", content=system), ChatMessage(role="user", content=user)],
            _atlas_purpose=purpose,
            think=False,
            num_predict=NUM_PREDICT,
            format=schema,
        )
    except Exception as exc:  # noqa: BLE001
        return None, f"{type(exc).__name__}: {exc}"[:200]
    text = str(getattr(resp, "text", None) or getattr(resp, "content", None) or "").strip()
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        return None, "parse_failed"
    return (obj, None) if isinstance(obj, dict) else (None, "not_an_object")


# --- R1 post-trade review ---------------------------------------------------

_FEATURE_KEYS = (
    "option_type", "underlying_type", "sma_margin", "rsi", "iv", "delta", "theta_per_day",
    "dte_days", "moneyness", "minutes_since_open", "day_of_week", "premium_pct_spot", "ce_pe_skew",
)


def _ist_clock(raw: Any) -> str | None:
    """Stored fills are UTC; the reviewer reads them as market-local time."""
    if not raw:
        return None
    try:
        ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    if ts.tzinfo is None:
        return None
    return ts.astimezone(_IST).strftime("%Y-%m-%d %H:%M IST")


def review_packet(episode: dict[str, Any]) -> dict[str, Any]:
    """What the reviewer may see: decide-time facts, the prediction, and the outcome."""
    from atlas.investment.cognitive.pattern_detector import DECIDE_TIME_DIMENSIONS, _derive

    ep = episode if isinstance(episode, dict) else {}
    feats = ep.get("features") if isinstance(ep.get("features"), dict) else {}
    derived = _derive(ep).get("_derived") or {}
    pred = ep.get("prediction") if isinstance(ep.get("prediction"), dict) else {}
    out = ep.get("outcome") if isinstance(ep.get("outcome"), dict) else {}
    err = ep.get("prediction_error") if isinstance(ep.get("prediction_error"), dict) else {}
    under = ep.get("underlier_movement") if isinstance(ep.get("underlier_movement"), dict) else {}
    fill = ep.get("fill") if isinstance(ep.get("fill"), dict) else {}
    attr = ep.get("attribution") if isinstance(ep.get("attribution"), dict) else {}
    return {
        "contract": ep.get("symbol"),
        "underlying": ep.get("underlying"),
        "day": ep.get("as_of_ist"),
        "decide_time_features": {k: feats[k] for k in _FEATURE_KEYS if feats.get(k) is not None},
        "feature_groups": {d: derived.get(d) for d in DECIDE_TIME_DIMENSIONS if derived.get(d)},
        "not_captured": list(feats.get("missing") or []),
        "prediction": {
            "expected_premium_direction": pred.get("expected_direction"),
            "expected_return": pred.get("expected_return"),
            "confidence": pred.get("confidence"),
            "horizon": pred.get("prediction_horizon"),
        },
        "fill": {
            "entry_premium": fill.get("entry_premium"),
            "exit_premium": fill.get("exit_premium"),
            "entry_ist": _ist_clock(fill.get("entry_at")),
            "exit_ist": _ist_clock(fill.get("exit_at")),
            "holding": derived.get("holding_bucket"),
        },
        "outcome": {
            "realized_pnl": out.get("realized_pnl"),
            "premium_return_pct": out.get("realized_return_pct"),
            "direction_match": err.get("direction_match") or out.get("direction_match"),
            "prediction_error_pct": err.get("error_pct"),
        },
        "underlier_session": {
            "return_pct": (under.get("session") or {}).get("return_pct") if isinstance(under.get("session"), dict) else None,
            "role": under.get("role"),
        },
        "attribution": {
            "helped": attr.get("helped"),
            "hurt": attr.get("hurt"),
            "unknown": attr.get("unknown"),
        },
    }


def review_schema() -> dict[str, Any]:
    from atlas.investment.cognitive.pattern_detector import DECIDE_TIME_DIMENSIONS

    return {
        "type": "object",
        "properties": {
            "what_happened": _SHORT,
            "main_driver": {
                "type": "string",
                "enum": ["underlier_move", "time_decay", "volatility", "entry_timing", "exit_timing", "unclear"],
            },
            "signal_or_luck": {"type": "string", "enum": ["signal", "luck", "unclear"]},
            "lesson_candidate": _SHORT,
            "data_missing": _SHORT_LIST,
            "testable_idea": {
                "type": "object",
                "properties": {
                    "dimension": {"type": "string", "enum": list(DECIDE_TIME_DIMENSIONS)},
                    "high_group": {"type": "string", "maxLength": 40},
                    "low_group": {"type": "string", "maxLength": 40},
                    "mechanism": _SHORT,
                },
                "required": ["dimension", "high_group", "low_group", "mechanism"],
            },
        },
        "required": ["what_happened", "main_driver", "signal_or_luck", "lesson_candidate", "data_missing"],
    }


def _reviews_path(data_dir: str | Path, laboratory_id: str) -> Path:
    return _root(data_dir, laboratory_id) / "trade_reviews.jsonl"


def load_trade_reviews(data_dir: str | Path | None, laboratory_id: str) -> list[dict[str, Any]]:
    if not data_dir:
        return []
    return _read_jsonl(_reviews_path(data_dir, laboratory_id))


def review_next_trade(
    data_dir: str | Path,
    *,
    laboratory_id: str,
    llm: Any,
    episodes: list[dict[str, Any]],
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Review the newest eligible round trip not yet reviewed. None when caught up."""
    todo = _unreviewed(data_dir, laboratory_id, episodes)
    if not todo:
        return None
    ep = todo[-1]
    packet = review_packet(ep)
    parsed, err = _chat_json(
        llm,
        REVIEW_SYSTEM,
        "PACKET:\n" + json.dumps(packet, default=str) + "\n\nReview this round trip. Do not repeat the packet.",
        review_schema(),
        "cognitive_trade_review",
    )
    row = {
        "version": VERSION,
        "kind": "TRADE_REVIEW",
        "laboratory_id": laboratory_id,
        "experience_id": ep.get("experience_id"),
        "contract": ep.get("symbol"),
        "as_of_ist": ep.get("as_of_ist"),
        "reviewed_at": _now_ist(now).isoformat(),
        "status": "reviewed" if parsed else "failed",
        "error": err,
        "review": parsed,
        "influence": INFLUENCE,
    }
    _append(_reviews_path(data_dir, laboratory_id) if parsed else _failures_path(data_dir, laboratory_id), row)
    return row


MAX_REVIEW_FAILURES = 2


def _failures_path(data_dir: str | Path, laboratory_id: str) -> Path:
    return _root(data_dir, laboratory_id) / "trade_review_failures.jsonl"


def _unreviewed(data_dir: str | Path, laboratory_id: str, episodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    done = {str(r.get("experience_id")) for r in load_trade_reviews(data_dir, laboratory_id)}
    fails: dict[str, int] = {}
    for r in _read_jsonl(_failures_path(data_dir, laboratory_id)):
        key = str(r.get("experience_id"))
        fails[key] = fails.get(key, 0) + 1
    return [
        e
        for e in episodes
        if e.get("experience_id")
        and str(e["experience_id"]) not in done
        and fails.get(str(e["experience_id"]), 0) < MAX_REVIEW_FAILURES
    ]


# --- R2 proposals -----------------------------------------------------------


def proposal_schema() -> dict[str, Any]:
    from atlas.investment.cognitive.pattern_detector import DECIDE_TIME_DIMENSIONS

    return {
        "type": "object",
        "properties": {
            "proposals": {
                "type": "array",
                "maxItems": MAX_PROPOSALS,
                "items": {
                    "type": "object",
                    "properties": {
                        "dimension": {"type": "string", "enum": list(DECIDE_TIME_DIMENSIONS)},
                        "high_group": {"type": "string", "maxLength": 40},
                        "low_group": {"type": "string", "maxLength": 40},
                        "mechanism": _SHORT,
                        "falsifier": _SHORT,
                    },
                    "required": ["dimension", "high_group", "low_group", "mechanism", "falsifier"],
                },
            }
        },
        "required": ["proposals"],
    }


def _asked_dimensions(data_dir: str | Path, laboratory_id: str) -> list[str]:
    try:
        from atlas.investment.hypothesis_learning import list_hypotheses

        return sorted(
            {
                str((row.get("extra") or {}).get("dimension") or "")
                for row in list_hypotheses(data_dir, laboratory_id=laboratory_id, include_world=False, limit=200)
                if isinstance(row.get("extra"), dict)
            }
            - {""}
        )
    except Exception:  # noqa: BLE001
        return []


def validate_proposal(
    proposal: dict[str, Any] | None,
    *,
    table: dict[str, dict[str, dict[str, int]]],
    asked: list[str] | set[str],
) -> tuple[bool, str]:
    """Deterministic checks. The LLM's confidence counts for nothing here."""
    from atlas.investment.cognitive.pattern_detector import DECIDE_TIME_DIMENSIONS

    p = proposal if isinstance(proposal, dict) else {}
    dim = str(p.get("dimension") or "")
    hi, lo = str(p.get("high_group") or ""), str(p.get("low_group") or "")
    if dim not in DECIDE_TIME_DIMENSIONS:
        return False, "not_a_decide_time_feature"
    groups = table.get(dim) or {}
    if hi not in groups or lo not in groups:
        return False, "group_not_in_data"
    if hi == lo:
        return False, "same_group"
    if dim in set(asked):
        return False, "already_asked"
    if not str(p.get("mechanism") or "").strip():
        return False, "no_mechanism"
    if not str(p.get("falsifier") or "").strip():
        return False, "no_falsifier"
    return True, "ok"


def _proposals_path(data_dir: str | Path, laboratory_id: str, day: str) -> Path:
    return _root(data_dir, laboratory_id) / "proposals" / f"{day}.jsonl"


def propose_hypotheses(
    data_dir: str | Path,
    *,
    laboratory_id: str,
    llm: Any,
    episodes: list[dict[str, Any]],
    now: datetime | None = None,
) -> dict[str, Any]:
    from atlas.investment.cognitive.pattern_detector import DECIDE_TIME_DIMENSIONS, dimension_table

    day = _now_ist(now).strftime("%Y-%m-%d")
    full = dimension_table(episodes)
    table = {d: g for d, g in full.items() if d in DECIDE_TIME_DIMENSIONS and len(g) >= 2}
    asked = _asked_dimensions(data_dir, laboratory_id)
    ideas = [
        (r.get("review") or {}).get("testable_idea")
        for r in load_trade_reviews(data_dir, laboratory_id)[-10:]
        if isinstance((r.get("review") or {}).get("testable_idea"), dict)
    ]
    constant = sorted(d for d in DECIDE_TIME_DIMENSIONS if d in full and len(full[d]) < 2)
    prompt = json.dumps(
        {
            "closed_episodes": sum(1 for _ in episodes),
            "metric": "direction_match: did the option premium move the way the entry predicted",
            "feature_table": table,
            "constant_in_this_sample": constant,
            "never_captured_yet": sorted(d for d in DECIDE_TIME_DIMENSIONS if d not in full),
            "already_asked": asked,
            "ideas_from_trade_reviews": ideas,
        },
        default=str,
    ) + "\n\nPropose up to three questions. Use only groups that appear in feature_table."
    parsed, err = _chat_json(llm, PROPOSAL_SYSTEM, prompt, proposal_schema(), "cognitive_hypothesis_proposal")
    receipt: dict[str, Any] = {"day": day, "status": "failed" if parsed is None else "proposed", "error": err,
                               "accepted": 0, "rejected": 0}
    if parsed is None:
        return receipt
    path = _proposals_path(data_dir, laboratory_id, day)
    props = (parsed.get("proposals") or [])[:MAX_PROPOSALS]
    if not props:
        _append(path, {"version": VERSION, "kind": "HYPOTHESIS_PROPOSAL", "laboratory_id": laboratory_id,
                       "proposed_at": _now_ist(now).isoformat(), "proposal": None,
                       "verdict": "none_offered", "reason": "empty", "source": SOURCE_LLM})
    for prop in props:
        ok, reason = validate_proposal(prop, table=table, asked=asked)
        _append(
            path,
            {
                "version": VERSION,
                "kind": "HYPOTHESIS_PROPOSAL",
                "laboratory_id": laboratory_id,
                "proposed_at": _now_ist(now).isoformat(),
                "proposal": prop,
                "verdict": "accepted" if ok else "rejected",
                "reason": reason,
                "source": SOURCE_LLM,
                "influence": INFLUENCE,
            },
        )
        receipt["accepted" if ok else "rejected"] += 1
    return receipt


def accepted_proposals(
    data_dir: str | Path | None, *, laboratory_id: str, as_of_ist: str
) -> list[dict[str, Any]]:
    """Accepted proposals from the last few days, newest first."""
    if not data_dir:
        return []
    root = _root(data_dir, laboratory_id) / "proposals"
    if not root.is_dir():
        return []
    files = sorted(p for p in root.glob("*.jsonl") if p.stem <= as_of_ist)[-PROPOSAL_LOOKBACK_DAYS:]
    out: list[dict[str, Any]] = []
    for path in reversed(files):
        for row in reversed(_read_jsonl(path)):
            if row.get("verdict") == "accepted" and isinstance(row.get("proposal"), dict):
                out.append(row)
    return out


def proposal_to_pattern(
    proposal: dict[str, Any],
    episodes: list[dict[str, Any]],
    *,
    laboratory_id: str,
    as_of_ist: str,
) -> dict[str, Any] | None:
    """Rebuild the proposal as a pattern from the data itself — the counts are ours."""
    from atlas.investment.cognitive.pattern_detector import (
        STATUS_CANDIDATE,
        VERSION as PATTERN_VERSION,
        _outcome_hit,
        confounds_for,
        dimension_table,
    )
    from atlas.investment.cognitive.stats import fisher_exact

    dim = str(proposal.get("dimension") or "")
    hi, lo = str(proposal.get("high_group") or ""), str(proposal.get("low_group") or "")
    groups = dimension_table(episodes).get(dim) or {}
    if hi not in groups or lo not in groups:
        return None
    detail = {
        k: {"n": v["n"], "hits": v["hits"], "hit_rate": round(v["hits"] / v["n"], 4) if v["n"] else None}
        for k, v in groups.items()
    }
    a, b = detail[hi], detail[lo]
    return {
        "version": PATTERN_VERSION,
        "kind": "CANDIDATE_PATTERN",
        "status": STATUS_CANDIDATE,
        "source": SOURCE_LLM,
        "mechanism": str(proposal.get("mechanism") or "")[:240],
        "llm_falsifier": str(proposal.get("falsifier") or "")[:240],
        "laboratory_id": laboratory_id,
        "as_of_ist": as_of_ist,
        "dimension": dim,
        "groups": detail,
        "n_total": sum(v["n"] for v in detail.values()),
        "high_group": hi,
        "low_group": lo,
        "split_delta": round(float(a["hit_rate"] or 0) - float(b["hit_rate"] or 0), 4),
        "p_value": round(fisher_exact(a["hits"], a["n"], b["hits"], b["n"]), 4),
        # In-sample size doesn't gate an LLM question: it is judged only on later trades.
        "thin_groups": [],
        "confounded_with": confounds_for(episodes, dim),
        "source_experience_ids": [
            str(r.get("experience_id")) for r in episodes if r.get("experience_id") and _outcome_hit(r) is not None
        ],
        "observation": (
            f"LLM-proposed question on {dim}: {hi} hit {a['hits']}/{a['n']}, "
            f"{lo} hit {b['hits']}/{b['n']} so far. Mechanism offered: {proposal.get('mechanism')}"
        ),
        "honesty": (
            "Proposed by the LLM, counted by code. Today's counts are context, not "
            "evidence; the verdict comes only from trades closed after this question."
        ),
    }


# --- one research step per tick ---------------------------------------------


MAX_CALLS_PER_STEP = 3
MAX_SECONDS_PER_STEP = 480.0


def run_research_step(
    data_dir: str | Path | None,
    *,
    laboratory_id: str,
    llm: Any | None,
    now: datetime | None = None,
    max_calls: int = MAX_CALLS_PER_STEP,
    max_seconds: float = MAX_SECONDS_PER_STEP,
) -> dict[str, Any]:
    """Review waiting trades first, then propose once a day. Bounded per call and per day."""
    receipt: dict[str, Any] = {"version": VERSION, "laboratory_id": laboratory_id, "actions": []}
    if not data_dir or llm is None:
        receipt["skipped"] = "no_llm_or_data_dir"
        return receipt
    if not off_hours(now):
        receipt["skipped"] = "market_hours"
        return receipt
    day = _now_ist(now).strftime("%Y-%m-%d")
    try:
        from atlas.investment.fno_closed_loop_dataset import load_closed_loop_episodes

        episodes = load_closed_loop_episodes(data_dir, laboratory_id=laboratory_id, eligible_only=True)
    except Exception:  # noqa: BLE001
        episodes = []
    if not episodes:
        receipt["skipped"] = "no_episodes"
        return receipt

    started = time.monotonic()
    for _ in range(max(0, int(max_calls))):
        if _calls_today(data_dir, laboratory_id, day) >= MAX_CALLS_PER_DAY:
            receipt["skipped"] = "budget"
            break
        if time.monotonic() - started >= max_seconds:
            receipt["skipped"] = "step_time_cap"
            break
        proposed = _proposals_path(data_dir, laboratory_id, day).is_file()
        # The last call of the day is kept for the proposal, so a busy trading day
        # can't crowd out the one step that asks new questions.
        room_for_review = proposed or _calls_today(data_dir, laboratory_id, day) < MAX_CALLS_PER_DAY - 1
        if room_for_review and _unreviewed(data_dir, laboratory_id, episodes):
            _spend(data_dir, laboratory_id, day)
            row = review_next_trade(data_dir, laboratory_id=laboratory_id, llm=llm, episodes=episodes, now=now) or {}
            receipt["actions"].append(
                {"action": "trade_review", "status": row.get("status"),
                 "experience_id": row.get("experience_id"), "error": row.get("error")}
            )
        elif not proposed:
            _spend(data_dir, laboratory_id, day)
            receipt["actions"].append(
                {"action": "propose", **propose_hypotheses(
                    data_dir, laboratory_id=laboratory_id, llm=llm, episodes=episodes, now=now)}
            )
        else:
            receipt["idle"] = "caught_up"
            break
    receipt["seconds"] = round(time.monotonic() - started, 1)
    return receipt
