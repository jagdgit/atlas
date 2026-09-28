"""OI-MDPH0 Phase 3 — L3 → belief candidate → subsequent test → L5 validation.

Implements the learning ladder without minting false L5s:

  L3 (chain-complete lesson)
    → L4 belief *candidate* (advice-only; never auto-active)
    → subsequent_test definition (N independent sessions / challenger set)
    → observe future outcomes
    → VALIDATED → L5  |  FALSIFIED / INCONCLUSIVE (stay < L5)

Hard law: do not claim L5 until subsequent_test has a result.
Does not place orders or increase capital.
"""

from __future__ import annotations

import json
import logging
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

VERSION = "learn.l3_l5.v1"
STORE_REL = Path("investment") / "l5_validation"
_IST = ZoneInfo("Asia/Kolkata")
_log = logging.getLogger("atlas.investment.l5_validation")

DEFAULT_SESSIONS_N = 5  # subsequent independent sessions to observe
STATUS_OPEN = "OPEN"
STATUS_PASS = "VALIDATED"
STATUS_FAIL = "FALSIFIED"
STATUS_INCONCLUSIVE = "INCONCLUSIVE"


def ist_today() -> str:
    return datetime.now(_IST).strftime("%Y-%m-%d")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe(s: str) -> str:
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in (s or ""))[:80]


def store_dir(data_dir: str | Path, laboratory_id: str) -> Path:
    return Path(data_dir) / STORE_REL / _safe(laboratory_id)


def _lesson_text(rec: dict[str, Any]) -> str:
    for k in ("update", "lesson"):
        v = rec.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()[:500]
    lessons = rec.get("lessons") if isinstance(rec.get("lessons"), dict) else {}
    for track, val in lessons.items():
        if isinstance(val, str) and val.strip():
            return f"[{track}] {val.strip()}"[:500]
    return ""


def belief_statement_from_l3(rec: dict[str, Any], *, laboratory_id: str) -> str:
    """Deterministic candidate belief text from an L3 learning record."""
    sym = str(rec.get("symbol") or "").upper() or "NAME"
    lesson = _lesson_text(rec)
    pe = rec.get("prediction") if isinstance(rec.get("prediction"), dict) else {}
    err = pe.get("error_pct")
    # Relative-opportunity / incumbent patterns → measurable edge claim
    if "relative_opportunity" in lesson.lower() or "next-rupee" in lesson.lower() or "vs " in lesson.lower():
        return (
            f"{sym} shows persistent relative intraday opportunity vs the competing "
            f"candidate set under current lab conditions ({laboratory_id}). "
            f"Lesson: {lesson}. "
            f"Validate: across next {DEFAULT_SESSIONS_N} independent sessions, "
            f"does {sym} outperform challengers+CASH more often than chance?"
        )[:500]
    if err is not None:
        return (
            f"{sym}: prediction error {err}% with lesson '{lesson}'. "
            f"Validate whether applying this lesson reduces absolute prediction error "
            f"over the next {DEFAULT_SESSIONS_N} independent closed outcomes."
        )[:500]
    return (
        f"{sym}: {lesson or 'L3 lesson'}. "
        f"Validate on next {DEFAULT_SESSIONS_N} independent sessions before L5."
    )[:500]


def define_subsequent_test(
    rec: dict[str, Any],
    *,
    laboratory_id: str,
    sessions_n: int = DEFAULT_SESSIONS_N,
) -> dict[str, Any]:
    """Machine-checkable test definition (not yet evaluated)."""
    sym = str(rec.get("symbol") or "").upper()
    lesson = _lesson_text(rec)
    kind = "relative_opportunity_win_rate"
    if "relative_opportunity" not in lesson.lower() and "next-rupee" not in lesson.lower():
        kind = "prediction_error_improves"
    return {
        "version": VERSION,
        "kind": kind,
        "symbol": sym,
        "laboratory_id": laboratory_id,
        "sessions_n": int(sessions_n),
        "metric": (
            "win_rate_vs_challenger_set"
            if kind == "relative_opportunity_win_rate"
            else "abs_prediction_error_mean"
        ),
        "pass_rule": (
            f"wins >= ceil({sessions_n}/2) among scored sessions where {sym} was eligible"
            if kind == "relative_opportunity_win_rate"
            else f"mean |error| over next {sessions_n} outcomes < baseline |error|"
        ),
        "baseline_error_pct": (
            (rec.get("prediction") or {}).get("error_pct")
            if isinstance(rec.get("prediction"), dict)
            else None
        ),
        "created_at": _now_iso(),
        "status": STATUS_OPEN,
        "observations": [],
        "result": None,
        "honesty": (
            "OPEN tests are not L5. L5 requires VALIDATED result from subsequent observations."
        ),
    }


def promote_l3_to_candidate(
    rec: dict[str, Any],
    *,
    laboratory_id: str,
    data_dir: str | Path | None = None,
    sessions_n: int = DEFAULT_SESSIONS_N,
) -> dict[str, Any]:
    """L3 → L4 candidate + OPEN subsequent_test. Never marks L5."""
    if not rec.get("chain_complete"):
        return {"ok": False, "error": "not_chain_complete", "level": rec.get("level")}
    level = str(rec.get("level") or "")
    if level not in {"L3", "L4", "L5", ""}:
        # Allow missing level if chain_complete
        pass
    statement = belief_statement_from_l3(rec, laboratory_id=laboratory_id)
    test = define_subsequent_test(rec, laboratory_id=laboratory_id, sessions_n=sessions_n)
    exp_id = str(rec.get("experience_id") or rec.get("id") or "")
    cid = hashlib.sha1(f"{laboratory_id}:{exp_id}:{statement[:80]}".encode()).hexdigest()[:16]
    candidate = {
        "version": VERSION,
        "id": f"BC-{cid}",
        "laboratory_id": laboratory_id,
        "source_record_id": rec.get("id"),
        "source_experience_id": exp_id,
        "symbol": rec.get("symbol"),
        "statement": statement,
        "status": "candidate",
        "influence": "advice_only",
        "never_auto_active": True,
        "level": "L4",
        "belief_update": "candidate",
        "subsequent_test": test,
        "created_at": _now_iso(),
        "category": "investment",
    }
    if data_dir:
        root = store_dir(data_dir, laboratory_id)
        root.mkdir(parents=True, exist_ok=True)
        path = root / f"{candidate['id']}.json"
        path.write_text(json.dumps(candidate, indent=2, default=str) + "\n", encoding="utf-8")
        latest = root / "_latest_candidates.json"
        try:
            bag = json.loads(latest.read_text(encoding="utf-8")) if latest.is_file() else {"items": []}
        except (OSError, json.JSONDecodeError):
            bag = {"items": []}
        items = [x for x in (bag.get("items") or []) if x.get("id") != candidate["id"]]
        items.insert(0, {"id": candidate["id"], "symbol": candidate.get("symbol"), "status": "candidate"})
        bag = {"version": VERSION, "updated_at": _now_iso(), "items": items[:50]}
        latest.write_text(json.dumps(bag, indent=2) + "\n", encoding="utf-8")
    return {"ok": True, "candidate": candidate, "level": "L4", "l5": False}


def record_test_observation(
    candidate: dict[str, Any],
    *,
    as_of_ist: str | None = None,
    won: bool | None = None,
    abs_error_pct: float | None = None,
    challenger_winner: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """Append one subsequent-session observation; evaluate if N reached."""
    day = as_of_ist or ist_today()
    test = dict(candidate.get("subsequent_test") or {})
    obs = list(test.get("observations") or [])
    # one observation per IST day
    obs = [o for o in obs if o.get("as_of_ist") != day]
    obs.append(
        {
            "as_of_ist": day,
            "won": won,
            "abs_error_pct": abs_error_pct,
            "challenger_winner": challenger_winner,
            "notes": notes,
            "recorded_at": _now_iso(),
        }
    )
    test["observations"] = obs
    need = int(test.get("sessions_n") or DEFAULT_SESSIONS_N)
    kind = str(test.get("kind") or "")
    result = None
    status = STATUS_OPEN
    if len(obs) >= need:
        if kind == "relative_opportunity_win_rate":
            scored = [o for o in obs if o.get("won") is not None]
            wins = sum(1 for o in scored if o.get("won") is True)
            need_wins = (need + 1) // 2
            if len(scored) < need:
                status = STATUS_INCONCLUSIVE
            elif wins >= need_wins:
                status = STATUS_PASS
                result = {"wins": wins, "n": len(scored), "need_wins": need_wins}
            else:
                status = STATUS_FAIL
                result = {"wins": wins, "n": len(scored), "need_wins": need_wins}
        else:
            errs = [float(o["abs_error_pct"]) for o in obs if o.get("abs_error_pct") is not None]
            baseline = test.get("baseline_error_pct")
            try:
                base = abs(float(baseline)) if baseline is not None else None
            except (TypeError, ValueError):
                base = None
            if len(errs) < need or base is None:
                status = STATUS_INCONCLUSIVE
            else:
                mean_err = sum(errs) / len(errs)
                if mean_err < base:
                    status = STATUS_PASS
                    result = {"mean_abs_error": mean_err, "baseline": base}
                else:
                    status = STATUS_FAIL
                    result = {"mean_abs_error": mean_err, "baseline": base}
    test["status"] = status
    test["result"] = result
    test["updated_at"] = _now_iso()
    out = dict(candidate)
    out["subsequent_test"] = test
    if status == STATUS_PASS:
        out["level"] = "L5"
        out["validation"] = {"status": STATUS_PASS, "result": result, "at": _now_iso()}
        out["subsequent_test_passed"] = True
    elif status in {STATUS_FAIL, STATUS_INCONCLUSIVE}:
        out["level"] = "L4"
        out["validation"] = {"status": status, "result": result, "at": _now_iso()}
        out["subsequent_test_passed"] = False
    return out


def promote_lab_l3_records(
    data_dir: str | Path,
    *,
    laboratory_id: str,
    as_of_ist: str | None = None,
) -> dict[str, Any]:
    """Scan learning audit for chain-complete L3s and ensure L4 candidates exist."""
    from atlas.investment.learning_audit import load_learning_audit

    aud = load_learning_audit(data_dir, laboratory_id=laboratory_id, as_of_ist=as_of_ist) or {}
    records = list(aud.get("learning_records") or [])
    created: list[dict[str, Any]] = []
    skipped = 0
    for rec in records:
        if not rec.get("chain_complete"):
            skipped += 1
            continue
        if str(rec.get("level") or "") == "L5":
            skipped += 1
            continue
        # Already has candidate belief_update + subsequent_test
        if rec.get("subsequent_test") and str(rec.get("belief_update") or "") == "candidate":
            skipped += 1
            continue
        out = promote_l3_to_candidate(rec, laboratory_id=laboratory_id, data_dir=data_dir)
        if out.get("ok"):
            created.append(out["candidate"])
        else:
            skipped += 1
    return {
        "ok": True,
        "version": VERSION,
        "laboratory_id": laboratory_id,
        "created_n": len(created),
        "skipped_n": skipped,
        "created_ids": [c.get("id") for c in created],
        "l5_claimed": False,
        "honesty": "Promotion creates L4 candidates only — L5 requires VALIDATED subsequent_test.",
    }


def list_candidates(data_dir: str | Path, laboratory_id: str) -> list[dict[str, Any]]:
    root = store_dir(data_dir, laboratory_id)
    if not root.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for p in sorted(root.glob("BC-*.json"), reverse=True):
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(doc, dict):
            out.append(doc)
    return out


def apply_validation_to_record(rec: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    """Merge candidate/validation onto a learning record for auditor re-score."""
    out = dict(rec)
    out["belief_update"] = "candidate"
    out["belief_candidate"] = {
        "id": candidate.get("id"),
        "statement": candidate.get("statement"),
        "status": candidate.get("status"),
    }
    out["subsequent_test"] = candidate.get("subsequent_test")
    if candidate.get("level") == "L5" or (
        isinstance(candidate.get("validation"), dict)
        and candidate["validation"].get("status") == STATUS_PASS
    ):
        out["level"] = "L5"
        out["validation"] = candidate.get("validation")
        out["subsequent_test"] = candidate.get("subsequent_test")
    else:
        out["level"] = "L4"
    return out


def observe_candidates_from_competition(
    data_dir: str | Path,
    *,
    laboratory_id: str,
    snap: dict[str, Any],
    as_of_ist: str | None = None,
) -> dict[str, Any]:
    """Append one subsequent-test observation from a competition snapshot.

    For relative_opportunity candidates: won=True iff candidate.symbol == snap.winner.
    Never claims L5 here — only updates OPEN tests via record_test_observation.
    """
    day = as_of_ist or ist_today()
    winner = str(snap.get("winner") or "").upper()
    updated = 0
    for cand in list_candidates(data_dir, laboratory_id):
        test = cand.get("subsequent_test") if isinstance(cand.get("subsequent_test"), dict) else {}
        if test.get("status") != STATUS_OPEN:
            continue
        if str(test.get("kind") or "") != "relative_opportunity_win_rate":
            continue
        sym = str(cand.get("symbol") or "").upper()
        if not sym:
            continue
        # Only score when symbol was in the candidate set (eligible)
        cset = {str(x).upper() for x in (snap.get("candidate_set") or [])}
        if cset and sym not in cset and sym.replace(".NS", "") not in {
            x.replace(".NS", "") for x in cset
        }:
            continue
        won = bool(winner) and (
            winner == sym
            or winner.replace(".NS", "") == sym.replace(".NS", "")
        )
        new_c = record_test_observation(
            cand,
            as_of_ist=day,
            won=won,
            challenger_winner=winner or None,
            notes="competition_snapshot",
        )
        # Persist updated candidate
        root = store_dir(data_dir, laboratory_id)
        root.mkdir(parents=True, exist_ok=True)
        path = root / f"{new_c['id']}.json"
        try:
            path.write_text(json.dumps(new_c, indent=2, default=str) + "\n", encoding="utf-8")
            updated += 1
        except OSError:
            _log.debug("l5 observe persist failed", exc_info=True)
    return {
        "ok": True,
        "updated_n": updated,
        "winner": winner,
        "as_of_ist": day,
        "l5_claimed": False,
        "honesty": "Observations only — L5 requires VALIDATED subsequent_test.",
    }
