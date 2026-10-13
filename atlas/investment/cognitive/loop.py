"""Cognitive Loop C9 — one nightly cycle, and the next question it leaves behind.

Runs the whole chain over the episodes already on disk: detect patterns, frame
hypotheses, admit or refuse them, read back any experiment results, route those into
the learning ladder, propose belief revisions that were earned, and finish by asking
what is still open.

Everything is BATCH work off the mail path. Every stage is individually guarded, so a
failure anywhere degrades the cycle to a recorded skip instead of taking down the tick
that calls it. Nothing here places orders, changes strategy, or promotes to live.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

VERSION = "cognitive.loop.v1"
KIND = "COGNITIVE_CYCLE"
STORE_REL = Path("investment") / "cognitive" / "cycles"

# One new question per cycle. The point is depth, not volume.
MAX_NEW_HYPOTHESES = 1

_IST = ZoneInfo("Asia/Kolkata")
_log = logging.getLogger("atlas.investment.cognitive.loop")


def ist_today() -> str:
    return datetime.now(_IST).strftime("%Y-%m-%d")


def run_cycle(
    data_dir: str | Path | None,
    *,
    laboratory_id: str = "india_fno_learner",
    as_of_ist: str | None = None,
    llm: Any | None = None,
    max_new_hypotheses: int = MAX_NEW_HYPOTHESES,
) -> dict[str, Any]:
    """One full pass. Returns a receipt; never raises into the caller's tick."""
    day = as_of_ist or ist_today()
    cycle: dict[str, Any] = {
        "version": VERSION,
        "kind": KIND,
        "laboratory_id": str(laboratory_id or ""),
        "as_of_ist": day,
        "stages": {},
        "episodes": 0,
        "patterns": 0,
        "hypotheses_created": 0,
        "admitted": 0,
        "refused": [],
        "results": [],
        "learning_candidates": 0,
        "belief_proposals": 0,
        "validated": 0,
        "open_questions": [],
        "mutates_strategy": False,
        "live_orders": False,
        "ran_at": datetime.now(_IST).isoformat(),
    }

    def stage(name: str, ok: bool, detail: Any = None) -> None:
        cycle["stages"][name] = {"ok": bool(ok), "detail": detail}

    # --- episodes ---------------------------------------------------------
    episodes: list[dict[str, Any]] = []
    try:
        from atlas.investment.fno_closed_loop_dataset import load_closed_loop_episodes

        episodes = load_closed_loop_episodes(data_dir, laboratory_id=laboratory_id, eligible_only=True)
        cycle["episodes"] = len(episodes)
        stage("episodes", bool(episodes), f"{len(episodes)} closed episodes")
    except Exception as exc:  # noqa: BLE001
        stage("episodes", False, type(exc).__name__)
        _log.debug("cognitive cycle: episode load failed", exc_info=True)

    if not episodes:
        cycle["honesty"] = (
            "No closed-loop episodes available — nothing to reason about. "
            "Not a failure, just an empty day."
        )
        persist_cycle(data_dir, cycle)
        return cycle

    # --- patterns ---------------------------------------------------------
    patterns: list[dict[str, Any]] = []
    try:
        from atlas.investment.cognitive.pattern_detector import (
            STATUS_CANDIDATE,
            detect_patterns,
            persist_patterns,
        )

        patterns = detect_patterns(
            episodes, laboratory_id=laboratory_id, as_of_ist=day
        )
        persist_patterns(data_dir, patterns, laboratory_id=laboratory_id, as_of_ist=day)
        cycle["patterns"] = len(patterns)
        cycle["pattern_dimensions"] = [p.get("dimension") for p in patterns]
        stage("patterns", True, f"{len(patterns)} candidate patterns")
        candidates = [p for p in patterns if p.get("status") == STATUS_CANDIDATE]
    except Exception as exc:  # noqa: BLE001
        stage("patterns", False, type(exc).__name__)
        _log.debug("cognitive cycle: pattern detection failed", exc_info=True)
        candidates = []

    symbols = sorted(
        {str(r.get("underlying") or "").upper() for r in episodes if r.get("underlying")}
    )

    # --- hypotheses + admission ------------------------------------------
    created = 0
    for pattern in candidates:
        if created >= max(0, int(max_new_hypotheses)):
            break
        try:
            from atlas.investment.cognitive.admission import ADMITTED, admit_hypothesis
            from atlas.investment.cognitive.hypothesis_engine import (
                build_hypothesis,
                duplicate_of,
                persist_hypothesis,
            )
            from atlas.investment.cognitive.queue import record_decision

            dim = str(pattern.get("dimension") or "")
            if duplicate_of(data_dir, laboratory_id=laboratory_id, dimension=dim):
                cycle["refused"].append({"dimension": dim, "reason": "duplicate_hypothesis"})
                continue

            hypo = build_hypothesis(pattern, laboratory_id=laboratory_id, llm=llm)
            if hypo is None:
                continue
            decision = admit_hypothesis(
                hypo,
                data_dir=data_dir,
                laboratory_id=laboratory_id,
                underlying_symbols=symbols,
            )
            if decision.get("status") != ADMITTED:
                cycle["refused"].append(
                    {
                        "dimension": dim,
                        "reason": decision.get("reason"),
                        "detail": decision.get("detail"),
                    }
                )
                record_decision(
                    data_dir,
                    laboratory_id=laboratory_id,
                    hypothesis_id=None,
                    decision=decision,
                    statement=hypo.get("statement"),
                )
                continue

            stored = persist_hypothesis(data_dir, hypo, laboratory_id=laboratory_id)
            if not stored.get("ok"):
                continue
            decision["falsifier"] = hypo.get("falsifier")
            record_decision(
                data_dir,
                laboratory_id=laboratory_id,
                hypothesis_id=stored.get("hypothesis_id"),
                decision=decision,
                statement=hypo.get("statement"),
            )
            created += 1
            cycle["admitted"] += 1
            cycle.setdefault("hypotheses", []).append(
                {
                    "hypothesis_id": stored.get("hypothesis_id"),
                    "dimension": dim,
                    "statement": hypo.get("statement"),
                    "confounded_with": (hypo.get("source_pattern") or {}).get(
                        "confounded_with"
                    ),
                }
            )
        except Exception as exc:  # noqa: BLE001
            stage("hypotheses", False, type(exc).__name__)
            _log.debug("cognitive cycle: hypothesis stage failed", exc_info=True)
            break
    cycle["hypotheses_created"] = created
    cycle["stages"].setdefault("hypotheses", {"ok": True, "detail": f"{created} created"})

    # --- results → learning candidates → belief proposals -----------------
    try:
        from atlas.investment.cognitive.beliefs import propose_revision
        from atlas.investment.cognitive.experiment_bridge import load_result
        from atlas.investment.cognitive.queue import load_queue
        from atlas.investment.cognitive.validator import (
            build_learning_candidate,
            apply_to_ladder,
            persist_candidate,
        )
        from atlas.investment.hypothesis_learning import get_hypothesis

        seen: set[str] = set()
        for row in load_queue(data_dir, laboratory_id=laboratory_id):
            hid = str(row.get("hypothesis_id") or "")
            if not hid or hid in seen:
                continue
            seen.add(hid)
            result = load_result(
                data_dir, laboratory_id=laboratory_id, hypothesis_id=hid
            )
            if not result:
                continue
            stored = get_hypothesis(data_dir, hid, laboratory_id=laboratory_id) or {}
            extra = stored.get("extra") if isinstance(stored.get("extra"), dict) else {}
            hypo = {
                "statement": stored.get("statement"),
                "falsifier": extra.get("falsifier"),
                "experiment_specs": extra.get("experiment_specs"),
                "source_pattern": extra.get("source_pattern"),
            }
            candidate = build_learning_candidate(
                result, hypothesis=hypo, laboratory_id=laboratory_id
            )
            if candidate is None:
                continue
            persist_candidate(data_dir, candidate)
            cycle["learning_candidates"] += 1
            cycle["results"].append(
                {
                    "hypothesis_id": hid,
                    "result": candidate.get("experiment_result"),
                    "ladder_outcome": candidate.get("ladder_outcome"),
                    "gap": candidate.get("gap"),
                }
            )
            apply_to_ladder(data_dir, candidate, laboratory_id=laboratory_id)
            proposal = propose_revision(
                data_dir, candidate, laboratory_id=laboratory_id
            )
            if proposal.get("proposed"):
                cycle["belief_proposals"] += 1
        stage("results", True, f"{cycle['learning_candidates']} learning candidates")
    except Exception as exc:  # noqa: BLE001
        stage("results", False, type(exc).__name__)
        _log.debug("cognitive cycle: result stage failed", exc_info=True)

    # --- validated count (read-only, from the existing ladder) ------------
    try:
        from atlas.investment.l5_validation import STATUS_PASS, list_candidates

        cycle["validated"] = sum(
            1
            for c in list_candidates(data_dir, laboratory_id)
            if (c.get("validation") or {}).get("status") == STATUS_PASS
        )
        stage("validation", True, f"{cycle['validated']} validated")
    except Exception as exc:  # noqa: BLE001
        stage("validation", False, type(exc).__name__)

    # --- C9: what is still open -------------------------------------------
    cycle["open_questions"] = _next_questions(data_dir, laboratory_id=laboratory_id)
    stage("next_questions", True, f"{len(cycle['open_questions'])} open")

    cycle["ladder"] = {
        "episodes": cycle["episodes"],
        "patterns": cycle["patterns"],
        "hypotheses": cycle["hypotheses_created"],
        "learning_candidates": cycle["learning_candidates"],
        "validated": cycle["validated"],
        "belief_proposals": cycle["belief_proposals"],
    }
    cycle["honesty"] = (
        "Episodes are not patterns, patterns are not hypotheses, hypotheses are not "
        "learnings, and learnings are not validated learnings. Each number above is "
        "only itself. No strategy, sizing, or order behaviour changed."
    )
    persist_cycle(data_dir, cycle)
    return cycle


def _next_questions(
    data_dir: str | Path | None, *, laboratory_id: str
) -> list[dict[str, Any]]:
    """Unresolved falsifiers, inconclusive tests, and refusals worth revisiting."""
    out: list[dict[str, Any]] = []
    try:
        from atlas.investment.cognitive.queue import (
            STATUS_ADMITTED,
            STATUS_DISPATCHED,
            load_queue,
        )

        latest: dict[str, dict[str, Any]] = {}
        for row in load_queue(data_dir, laboratory_id=laboratory_id):
            hid = str(row.get("hypothesis_id") or "")
            if hid:
                latest[hid] = row
        for hid, row in latest.items():
            if row.get("status") in {STATUS_ADMITTED, STATUS_DISPATCHED}:
                out.append(
                    {
                        "question": f"awaiting result on {row.get('dimension')}",
                        "hypothesis_id": hid,
                        "why": "experiment queued but no result recorded yet",
                    }
                )
    except Exception:  # noqa: BLE001
        _log.debug("next questions: queue scan skipped", exc_info=True)

    try:
        from atlas.investment.cognitive.experiment_bridge import (
            RESULT_INCONCLUSIVE,
            RESULT_NOT_EVALUABLE,
        )
        from atlas.investment.cognitive.validator import load_candidates

        for cand in load_candidates(data_dir, laboratory_id=laboratory_id):
            result = cand.get("experiment_result")
            if result == RESULT_INCONCLUSIVE:
                out.append(
                    {
                        "question": (
                            f"{cand.get('dimension')}: effect was {cand.get('gap')} vs a "
                            f"required {cand.get('min_effect')} — does it hold with more sessions?"
                        ),
                        "hypothesis_id": cand.get("hypothesis_id"),
                        "why": "inconclusive: needs a larger independent sample",
                    }
                )
            elif result == RESULT_NOT_EVALUABLE:
                out.append(
                    {
                        "question": (
                            f"{cand.get('dimension')}: what would have to be stored to "
                            "make this testable?"
                        ),
                        "hypothesis_id": cand.get("hypothesis_id"),
                        "why": f"not evaluable: {cand.get('experiment_reason')}",
                    }
                )
            for confound in cand.get("confounded_with") or []:
                out.append(
                    {
                        "question": (
                            f"does {cand.get('dimension')} or {confound} explain the "
                            "split? they move together in this sample"
                        ),
                        "hypothesis_id": cand.get("hypothesis_id"),
                        "why": "confounded: needs a sample where they come apart",
                    }
                )
    except Exception:  # noqa: BLE001
        _log.debug("next questions: candidate scan skipped", exc_info=True)

    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in out:
        key = str(row.get("question"))
        if key not in seen:
            seen.add(key)
            deduped.append(row)
    return deduped[:12]


def persist_cycle(
    data_dir: str | Path | None, cycle: dict[str, Any] | None
) -> dict[str, Any]:
    if not data_dir or not isinstance(cycle, dict):
        return {"ok": False, "reason": "missing_args"}
    try:
        path = (
            Path(data_dir)
            / STORE_REL
            / str(cycle.get("laboratory_id") or "")
            / f"{cycle.get('as_of_ist')}.json"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cycle, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"ok": True, "path": str(path)}
    except Exception as exc:  # noqa: BLE001
        _log.debug("cognitive cycle persist failed", exc_info=True)
        return {"ok": False, "reason": type(exc).__name__}


def load_cycle(
    data_dir: str | Path | None,
    *,
    laboratory_id: str,
    as_of_ist: str | None = None,
) -> dict[str, Any] | None:
    if not data_dir:
        return None
    path = (
        Path(data_dir)
        / STORE_REL
        / str(laboratory_id)
        / f"{as_of_ist or ist_today()}.json"
    )
    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    return doc if isinstance(doc, dict) else None


def format_cognitive_loop_section(cycle: dict[str, Any] | None) -> list[str]:
    """Evening-digest lines. Reads a persisted cycle; computes nothing."""
    lines = ["Cognitive loop (Loop B):"]
    if not isinstance(cycle, dict):
        lines.append("  no cycle run yet — no questions asked, no learnings claimed")
        return lines
    ladder = cycle.get("ladder") or {}
    lines.append(
        "  episodes={episodes} patterns={patterns} hypotheses={hypotheses} "
        "candidates={learning_candidates} validated={validated}".format(
            episodes=ladder.get("episodes", 0),
            patterns=ladder.get("patterns", 0),
            hypotheses=ladder.get("hypotheses", 0),
            learning_candidates=ladder.get("learning_candidates", 0),
            validated=ladder.get("validated", 0),
        )
    )
    for row in (cycle.get("hypotheses") or [])[:2]:
        lines.append(f"  asked [{row.get('dimension')}]: {row.get('statement')}")
    for row in (cycle.get("results") or [])[:3]:
        lines.append(
            f"  result [{row.get('hypothesis_id', '')[:8]}]: {row.get('result')} "
            f"(gap={row.get('gap')})"
        )
    for row in (cycle.get("refused") or [])[:3]:
        lines.append(f"  refused [{row.get('dimension')}]: {row.get('reason')}")
    for row in (cycle.get("open_questions") or [])[:3]:
        lines.append(f"  open: {row.get('question')}")
    return lines
