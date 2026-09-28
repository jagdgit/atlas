"""CLC.1–CLC.2 — retrieve → cite → bounded influence (no LLM authority).

Lessons may change ranking/caution within caps. They never emit BUY/SELL
and cannot override L0 gates (PLC.A, session, concentration, completeness).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

VERSION = "clc.lesson_influence.v1"

OPTION_SCORE_CAP = 0.25
RANKING_CAP = 0.20
POSITIVE_OPTION_CAP = 0.10

LAYER_AUTHOR_CLAIM = "AUTHOR_CLAIM"
LAYER_HYPOTHESIS = "ATLAS_HYPOTHESIS"
LAYER_EXPERIMENT = "EXPERIMENT_RESULT"
LAYER_VALIDATED = "VALIDATED_MARKET_LESSON"
LAYER_BELIEF = "ACTIVE_BELIEF"

KIND_FINDING = "finding"
KIND_FEL = "fel_result"
KIND_HYPOTHESIS = "hypothesis"
KIND_EXPERIENCE = "experience"
KIND_BELIEF = "belief"

E001_LESSON_ID = "L-E001-buy_name-vol-accel"
E001_EXPERIMENT_ID = "E001-buy_name-vol-accel"
E001_HYPOTHESIS_ID = "H-buy_name-vol-accel"
E001_FEATURE_ID = "volume_acceleration_20d"
E001_FINDING_ID = "F-E001-vol-accel-negative"
E001_STATEMENT = (
    "Volume acceleration did not add economic information beyond momentum and "
    "relative strength for buy_name after 15 bps costs (E001, 79 folds, 2018–). "
    "Do not treat vol-accel as a reason to buy."
)

SETUP_X_FINDING_ID = "F-002118"
SETUP_X_STATEMENT = "Setup X performed poorly when regime Y was present."

INFLUENCE_ADVICE = "advice_only"
INFLUENCE_CITED = "cited"
INFLUENCE_BOUNDED = "cited_bounded"

# Provenance — L2 owns deltas; Core owns review_status (COG-3).
INFLUENCE_SOURCE_DETERMINISTIC = "deterministic"
INFLUENCE_SOURCE_COGNITIVE_REVIEWED = "cognitive_reviewed"
INFLUENCE_SOURCE_COGNITIVE_UNREVIEWED = "cognitive_unreviewed"
INFLUENCE_SOURCE_POLICY = "policy"

CROSS_THEME_TOKENS = (
    "hidden_state",
    "hidden state",
    "complexity",
    "opaque",
    "predictability",
    "feedback loop",
)

_log = logging.getLogger("atlas.investment.lesson_influence")
STORE_REL = Path("investment") / "fel" / "lessons"


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(value)))


def clamp_option_delta(delta: float) -> float:
    return clamp(delta, -OPTION_SCORE_CAP, OPTION_SCORE_CAP)


def clamp_ranking_delta(delta: float) -> float:
    return clamp(delta, -RANKING_CAP, RANKING_CAP)


def _norm(text: Any) -> str:
    return " ".join(str(text or "").lower().replace("_", " ").split())


def _blob(*parts: Any) -> str:
    return _norm(" ".join(str(p) for p in parts if p is not None and str(p).strip()))


def cross_themes_hit(query: str) -> bool:
    q = _norm(query)
    return any(tok in q for tok in CROSS_THEME_TOKENS)


def consult_domains_for_query(query: str) -> list[str]:
    domains = ["market"]
    if cross_themes_hit(query):
        domains.append("cross")
    return domains


def candidate_blob(candidate: dict[str, Any] | None) -> str:
    c = candidate if isinstance(candidate, dict) else {}
    feats = c.get("features") or []
    feat_s = " ".join(str(f) for f in feats)
    tags = c.get("regime_tags") or []
    tag_s = " ".join(str(t) for t in tags)
    return _blob(
        c.get("query"),
        c.get("decision_type"),
        c.get("action"),
        c.get("strategy_tag"),
        c.get("setup_tag"),
        c.get("regime"),
        feat_s,
        tag_s,
        c.get("symbol"),
    )


def _e001_query_hit(blob: str) -> bool:
    return any(
        tok in blob
        for tok in (
            "volume acceleration",
            "vol accel",
            "vol-accel",
            "volumeacceleration",
            "volume acceleration 20d",
        )
    )


def _setup_x_candidate_hit(candidate: dict[str, Any] | None, blob: str) -> bool:
    c = candidate if isinstance(candidate, dict) else {}
    setup = _norm(c.get("setup_tag") or c.get("setup") or "")
    regime = _norm(c.get("regime") or "")
    tags = [_norm(t) for t in (c.get("regime_tags") or [])]
    strategy = _norm(c.get("strategy_tag") or "")
    setup_ok = setup in {"x", "setup x"} or "setup x" in blob or "setup_x" in strategy.replace(
        " ", "_"
    )
    regime_ok = (
        regime in {"y", "regime y"}
        or "regime y" in blob
        or any(t in {"y", "regime y"} for t in tags)
        or " y" in f" {regime} "
    )
    return setup_ok and regime_ok


def _is_buy_name(candidate: dict[str, Any] | None, blob: str) -> bool:
    c = candidate if isinstance(candidate, dict) else {}
    dt = _norm(c.get("decision_type") or "")
    if dt in {"buy name", "buy_name"}:
        return True
    if "buy name" in blob:
        return True
    action = _norm(c.get("action") or "")
    return action == "buy" and "volume" in blob


def _uses_vol_accel(candidate: dict[str, Any] | None, blob: str) -> bool:
    c = candidate if isinstance(candidate, dict) else {}
    feats = [_norm(f) for f in (c.get("features") or [])]
    if any("volume acceleration" in f or "vol accel" in f for f in feats):
        return True
    return "volume acceleration" in blob or "vol accel" in blob


def _layer_allows_l2(layer: str) -> bool:
    return layer in {LAYER_VALIDATED, LAYER_BELIEF}


def _kind_from_layer(layer: str, default: str = KIND_FINDING) -> str:
    return {
        LAYER_AUTHOR_CLAIM: KIND_FINDING,
        LAYER_HYPOTHESIS: KIND_HYPOTHESIS,
        LAYER_EXPERIMENT: KIND_FEL,
        LAYER_VALIDATED: KIND_FINDING,
        LAYER_BELIEF: KIND_BELIEF,
    }.get(layer, default)


def canonical_e001_lesson(*, n_folds: int | None = 79) -> dict[str, Any]:
    folds = int(n_folds or 79)
    statement = E001_STATEMENT
    if folds != 79:
        statement = statement.replace("79 folds", f"{folds} folds")
    try:
        from atlas.reasoning.cognitive_contract import (
            EFFECT_DIR_NEGATIVE,
            EFFECT_TARGET_BUY_SCORE,
            expected_effect,
        )

        ee = expected_effect(
            target=EFFECT_TARGET_BUY_SCORE,
            direction=EFFECT_DIR_NEGATIVE,
            confidence=0.9,
        )
    except Exception:  # noqa: BLE001
        ee = {
            "target": "buy_score",
            "direction": "negative",
            "confidence": 0.9,
        }
    return {
        "id": E001_LESSON_ID,
        "kind": KIND_FEL,
        "statement": statement,
        "layer": LAYER_VALIDATED,
        "sign": -1,
        "expected_effect": ee,
        "experiment_id": E001_EXPERIMENT_ID,
        "hypothesis_id": E001_HYPOTHESIS_ID,
        "feature_id": E001_FEATURE_ID,
        "finding_id": E001_FINDING_ID,
        "decision_eligible": False,
        "lesson_eligible": True,
        "n_folds": folds,
        "match_tokens": ("volume acceleration", "buy_name", "vol-accel"),
    }


def canonical_setup_x_lesson() -> dict[str, Any]:
    return {
        "id": SETUP_X_FINDING_ID,
        "kind": KIND_FINDING,
        "statement": SETUP_X_STATEMENT,
        "layer": LAYER_VALIDATED,
        "sign": -1,
        "expected_effect": {
            "target": "buy_score",
            "direction": "negative",
            "confidence": 0.7,
        },
        "match_tokens": ("setup x", "regime y"),
    }


def load_e001_from_disk(data_dir: str | Path | None) -> dict[str, Any] | None:
    """Overlay fold count from a sealed E001 JSON. Never reruns the walk-forward."""
    if not data_dir:
        return None
    try:
        from atlas.investment.fel.experiments.store import load_experiment

        doc = load_experiment(data_dir, E001_EXPERIMENT_ID)
    except Exception:  # noqa: BLE001
        doc = None
    if not isinstance(doc, dict):
        path = Path(data_dir) / STORE_REL / f"{E001_LESSON_ID}.json"
        if path.is_file():
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                doc = None
    if not isinstance(doc, dict):
        return None
    ev = doc.get("evaluation") if isinstance(doc.get("evaluation"), dict) else {}
    n_folds = ev.get("n_folds") or doc.get("n_folds")
    try:
        n_folds_i = int(n_folds) if n_folds is not None else 79
    except (TypeError, ValueError):
        n_folds_i = 79
    lesson = canonical_e001_lesson(n_folds=n_folds_i)
    result = str((doc.get("result") or doc.get("belief") or {}).get("status") or doc.get("result") or "")
    if result.lower() in {"invalid"}:
        lesson["layer"] = LAYER_EXPERIMENT
        lesson["lesson_eligible"] = False
    return lesson


def persist_canonical_e001_lesson(data_dir: str | Path | None) -> Path | None:
    if not data_dir:
        return None
    root = Path(data_dir) / STORE_REL
    try:
        root.mkdir(parents=True, exist_ok=True)
        path = root / f"{E001_LESSON_ID}.json"
        if path.is_file():
            return path
        payload = {
            "store_version": VERSION,
            **canonical_e001_lesson(),
            "live_control": False,
        }
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)
        return path
    except OSError:
        _log.debug("e001 lesson persist failed", exc_info=True)
        return None


def catalog_lessons(
    *,
    data_dir: str | Path | None = None,
    extra: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _add(row: dict[str, Any] | None) -> None:
        if not isinstance(row, dict) or not row.get("id"):
            return
        key = str(row["id"])
        if key in seen:
            return
        seen.add(key)
        out.append(dict(row))

    disk = load_e001_from_disk(data_dir)
    _add(disk or canonical_e001_lesson())
    for row in extra or []:
        _add(row)
    return out


def _infer_layer(item: dict[str, Any]) -> str:
    raw = str(item.get("layer") or item.get("epistemic_layer") or "").strip()
    if raw in {
        LAYER_AUTHOR_CLAIM,
        LAYER_HYPOTHESIS,
        LAYER_EXPERIMENT,
        LAYER_VALIDATED,
        LAYER_BELIEF,
    }:
        return raw
    claim = str(item.get("truth_kind") or item.get("claim_type") or item.get("kind") or "").lower()
    if "author" in claim or claim == "claim":
        return LAYER_AUTHOR_CLAIM
    status = str(item.get("status") or "").lower()
    if status in {"open", "candidate"} and item.get("kind") == KIND_HYPOTHESIS:
        return LAYER_HYPOTHESIS
    n = item.get("n") or item.get("n_folds") or item.get("sample_n")
    try:
        n_i = int(n) if n is not None else None
    except (TypeError, ValueError):
        n_i = None
    if n_i == 1 or str(item.get("result") or "").lower() == "invalid":
        return LAYER_EXPERIMENT
    if item.get("lesson_eligible") is False and item.get("kind") == KIND_FEL:
        return LAYER_EXPERIMENT
    if item.get("kind") == KIND_BELIEF or item.get("belief_key"):
        return LAYER_BELIEF
    if item.get("layer") == LAYER_VALIDATED or item.get("lesson_eligible") is True:
        return LAYER_VALIDATED
    return str(item.get("layer") or LAYER_EXPERIMENT)


def _sign_of(item: dict[str, Any]) -> int:
    try:
        s = int(item.get("sign") or 0)
        if s in (-1, 0, 1):
            return s
    except (TypeError, ValueError):
        pass
    blob = _norm(item.get("statement") or item.get("lesson") or "")
    negative = any(
        tok in blob
        for tok in (
            "did not",
            "poorly",
            "worse",
            "failed",
            "do not treat",
            "negative",
            "underperform",
        )
    )
    positive = any(tok in blob for tok in ("improved", "beats baseline", "positive expectancy"))
    if negative and not positive:
        return -1
    if positive and not negative:
        return 1
    return 0


def retrieved_from_finding_hit(hit: Any) -> dict[str, Any] | None:
    if isinstance(hit, dict):
        content = str(hit.get("content") or hit.get("statement") or "")
        fid = str(
            hit.get("finding_id")
            or hit.get("id")
            or hit.get("canonical_id")
            or ""
        )
        chunk = str(hit.get("chunk_id") or "")
        if not fid and chunk.startswith("finding:"):
            fid = chunk.split(":", 1)[1]
    else:
        content = str(getattr(hit, "content", "") or "")
        fid = str(getattr(hit, "finding_id", "") or getattr(hit, "id", "") or "")
        chunk = str(getattr(hit, "chunk_id", "") or "")
        if not fid and chunk.startswith("finding:"):
            fid = chunk.split(":", 1)[1]
    if not content and not fid:
        return None
    layer = LAYER_VALIDATED
    low = content.lower()
    if "author claim" in low or "author claims" in low:
        layer = LAYER_AUTHOR_CLAIM
    if SETUP_X_STATEMENT[:20].lower() in low or "setup x performed poorly" in low:
        fid = fid or SETUP_X_FINDING_ID
        layer = LAYER_VALIDATED
    if "volume acceleration did not" in low or E001_LESSON_ID in fid or E001_FINDING_ID in fid:
        fid = fid or E001_FINDING_ID
        layer = LAYER_VALIDATED
    return {
        "id": fid or "finding",
        "kind": KIND_FINDING,
        "statement": content[:400],
        "layer": layer,
        "sign": _sign_of({"statement": content}),
    }


def retrieved_from_experience(row: Any) -> dict[str, Any] | None:
    rec = row if isinstance(row, dict) else {}
    journal = rec.get("journal") if isinstance(rec.get("journal"), dict) else {}
    lesson = str(journal.get("lesson") or rec.get("lesson") or rec.get("title") or "")
    eid = rec.get("id") or journal.get("id")
    if not lesson and not eid:
        return None
    return {
        "id": str(eid or "experience"),
        "kind": KIND_EXPERIENCE,
        "statement": lesson[:400],
        "layer": LAYER_EXPERIMENT,
        "sign": _sign_of({"statement": lesson}),
    }


def retrieved_from_belief(row: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(row, dict):
        return None
    bid = row.get("id") or row.get("belief_key")
    statement = str(row.get("statement") or "")
    if not bid:
        return None
    return {
        "id": str(bid),
        "kind": KIND_BELIEF,
        "statement": statement[:400],
        "layer": LAYER_BELIEF,
        "sign": 0,
        "belief_key": row.get("belief_key"),
        "domain": row.get("domain"),
        "status": row.get("status"),
    }


def match_lessons(
    *,
    candidate: dict[str, Any] | None,
    retrieved: list[dict[str, Any]] | None = None,
    query: str = "",
) -> list[dict[str, Any]]:
    """Return cited lesson_refs. L2 deltas are already per-lesson (pre-sum clamp)."""
    c = candidate if isinstance(candidate, dict) else {}
    blob = _blob(candidate_blob(c), query)
    matched: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _cite(
        item: dict[str, Any],
        *,
        match: str,
        option_delta: float = 0.0,
        ranking_delta: float = 0.0,
    ) -> None:
        lid = str(item.get("id") or "")
        if not lid or lid in seen:
            return
        seen.add(lid)
        layer = _infer_layer(item)
        sign = int(item.get("sign") if item.get("sign") in (-1, 0, 1) else _sign_of(item))
        l2_ok = _layer_allows_l2(layer) and item.get("lesson_eligible", True) is not False
        if layer == LAYER_AUTHOR_CLAIM or layer == LAYER_HYPOTHESIS:
            l2_ok = False
        if layer == LAYER_EXPERIMENT:
            l2_ok = False
        opt = clamp_option_delta(option_delta) if l2_ok else 0.0
        rank = clamp_ranking_delta(ranking_delta) if l2_ok else 0.0
        matched.append(
            {
                "id": lid,
                "kind": str(item.get("kind") or _kind_from_layer(layer)),
                "statement": str(item.get("statement") or "")[:400],
                "match": match,
                "layer": layer,
                "sign": sign,
                "l2_option": opt,
                "l2_ranking": rank,
            }
        )

    for item in retrieved or []:
        if not isinstance(item, dict):
            continue
        iid = str(item.get("id") or "")
        stmt = _norm(item.get("statement") or "")
        is_e001 = iid in {E001_LESSON_ID, E001_FINDING_ID, E001_EXPERIMENT_ID, E001_HYPOTHESIS_ID} or (
            "volume acceleration did not" in stmt
        )
        is_setup = iid == SETUP_X_FINDING_ID or "setup x performed poorly" in stmt
        if is_e001 and (_e001_query_hit(blob) or _is_buy_name(c, blob) or _uses_vol_accel(c, blob)):
            buy_name = _is_buy_name(c, blob)
            uses_feat = _uses_vol_accel(c, blob)
            opt = -OPTION_SCORE_CAP if buy_name or uses_feat else 0.0
            rank = -RANKING_CAP if uses_feat or buy_name else 0.0
            row = dict(item)
            row.setdefault("layer", LAYER_VALIDATED)
            row.setdefault("sign", -1)
            row.setdefault("kind", KIND_FEL)
            _cite(
                row,
                match="e001_vol_accel_buy_name",
                option_delta=opt,
                ranking_delta=rank,
            )
            continue
        if is_setup and _setup_x_candidate_hit(c, blob):
            row = dict(item)
            row.setdefault("layer", LAYER_VALIDATED)
            row.setdefault("sign", -1)
            _cite(
                row,
                match="setup_x_regime_y",
                option_delta=-OPTION_SCORE_CAP,
                ranking_delta=0.0,
            )
            continue
        layer = _infer_layer(item)
        if layer == LAYER_AUTHOR_CLAIM:
            if stmt and any(tok in blob for tok in stmt.split()[:8] if len(tok) > 4):
                _cite(item, match="author_claim_cite_only")
            elif "volume" in stmt and "volume" in blob:
                _cite(item, match="author_claim_cite_only")
            continue
        if layer == LAYER_BELIEF:
            # Consult already stamps beliefs on belief_context. Do not dump seeds into lesson_refs.
            continue
        if layer == LAYER_EXPERIMENT:
            if stmt and (
                stmt[:40] in blob
                or any(tok in blob for tok in ("round trip", "n=1", "invalid"))
            ):
                _cite(item, match="experiment_cite_only")
            continue
        if layer == LAYER_HYPOTHESIS:
            _cite(item, match="hypothesis_cite_only")
            continue
        if layer == LAYER_VALIDATED:
            sign = _sign_of(item)
            if sign and stmt and (stmt[:24] in blob or iid in blob):
                opt = -OPTION_SCORE_CAP if sign < 0 else POSITIVE_OPTION_CAP
                _cite(item, match="validated_lesson", option_delta=opt)

    return matched


def l2_totals(lessons: list[dict[str, Any]] | None) -> dict[str, float]:
    option = 0.0
    ranking = 0.0
    for row in lessons or []:
        if not isinstance(row, dict):
            continue
        try:
            option += float(row.get("l2_option") or 0.0)
        except (TypeError, ValueError):
            pass
        try:
            ranking += float(row.get("l2_ranking") or 0.0)
        except (TypeError, ValueError):
            pass
    return {
        "option": clamp_option_delta(option),
        "ranking": clamp_ranking_delta(ranking),
    }


def experience_ref_ids(lessons: list[dict[str, Any]] | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for row in lessons or []:
        if not isinstance(row, dict):
            continue
        lid = str(row.get("id") or "").strip()
        if lid and lid not in seen:
            seen.add(lid)
            out.append(lid)
    return out


def explanation_lines(lessons: list[dict[str, Any]] | None) -> list[str]:
    lines: list[str] = []
    for row in lessons or []:
        if not isinstance(row, dict):
            continue
        lid = row.get("id")
        stmt = str(row.get("statement") or "")[:160]
        match = row.get("match") or ""
        l2 = row.get("l2_option") or row.get("l2_ranking")
        bit = f"lesson {lid}"
        if match:
            bit += f" ({match})"
        if l2:
            bit += f" L2={l2}"
        if stmt:
            bit += f": {stmt}"
        lines.append(bit)
    return lines


def stamp_belief_context(
    ctx: dict[str, Any],
    lessons: list[dict[str, Any]] | None,
    *,
    cognitive_review_status: str | None = None,
    influence_source: str = INFLUENCE_SOURCE_DETERMINISTIC,
) -> dict[str, Any]:
    out = dict(ctx) if isinstance(ctx, dict) else {}
    refs = list(lessons or [])
    out["lesson_refs"] = refs
    out["experience_refs"] = experience_ref_ids(refs)
    totals = l2_totals(refs)
    out["l2"] = totals
    out["influence_events"] = build_influence_events(
        refs,
        cognitive_review_status=cognitive_review_status,
        influence_source=influence_source,
    )
    if refs and (totals["option"] or totals["ranking"]):
        out["influence"] = INFLUENCE_BOUNDED
        out["no_match"] = False
        out.pop("no_match_reason", None)
        out["note"] = (
            f"{len(refs)} lesson(s) cited; bounded L2 "
            f"option={totals['option']:+.2f} ranking={totals['ranking']:+.2f} "
            f"(caps ±{OPTION_SCORE_CAP}/±{RANKING_CAP})."
        )
    elif refs:
        out["influence"] = INFLUENCE_CITED
        out["no_match"] = False
        out.pop("no_match_reason", None)
        out["note"] = f"{len(refs)} lesson(s) cited (L1 only; no score change)."
    else:
        # CLC.6 — empty refs must be an honest no_match, not a silent drop.
        out["no_match"] = True
        out["no_match_reason"] = "no validated lesson matched this decide state"
        note = str(out.get("note") or "").strip()
        extra = "No matching lesson (honest no_match)."
        if extra not in note:
            out["note"] = f"{note} {extra}".strip() if note else extra
    return out


def build_influence_events(
    lessons: list[dict[str, Any]] | None,
    *,
    cognitive_review_status: str | None = None,
    influence_source: str = INFLUENCE_SOURCE_DETERMINISTIC,
) -> list[dict[str, Any]]:
    """Stamp L2 provenance without moving influence into Cognitive Core."""
    try:
        from atlas.reasoning.cognitive_contract import influence_event
    except Exception:  # noqa: BLE001
        influence_event = None  # type: ignore[assignment]
    events: list[dict[str, Any]] = []
    for row in lessons or []:
        if not isinstance(row, dict):
            continue
        lid = str(row.get("id") or "").strip()
        if not lid:
            continue
        try:
            opt = float(row.get("l2_option") or 0.0)
        except (TypeError, ValueError):
            opt = 0.0
        try:
            rank = float(row.get("l2_ranking") or 0.0)
        except (TypeError, ValueError):
            rank = 0.0
        src = str(row.get("influence_source") or influence_source)
        if influence_event is not None:
            events.append(
                influence_event(
                    lesson_id=lid,
                    bounded_delta={"option": opt, "ranking": rank},
                    influence_source=src,
                    cognitive_review_status=cognitive_review_status
                    or row.get("cognitive_review_status"),
                )
            )
        else:
            events.append(
                {
                    "influence_source": src,
                    "lesson_id": lid,
                    "cognitive_review_status": cognitive_review_status,
                    "bounded_delta": {"option": opt, "ranking": rank},
                }
            )
    return events[:24]


def apply_to_options(
    options: list[Any],
    lessons: list[dict[str, Any]] | None,
    *,
    cognitive_review_status: str | None = None,
    influence_source: str = INFLUENCE_SOURCE_DETERMINISTIC,
) -> list[Any]:
    """Subtract/add clamped option score on buy:* keys. Mutates options."""
    events = build_influence_events(
        lessons,
        cognitive_review_status=cognitive_review_status,
        influence_source=influence_source,
    )
    # Sum only non-zeroed events (cognitive_unreviewed zeros deltas).
    option_delta = 0.0
    for ev in events:
        try:
            option_delta += float((ev.get("bounded_delta") or {}).get("option") or 0.0)
        except (TypeError, ValueError):
            pass
    option_delta = clamp_option_delta(option_delta)
    # Fallback: if no events built, use classic totals (deterministic path).
    if not events:
        option_delta = l2_totals(lessons)["option"]
    ids = experience_ref_ids(lessons)
    lines = explanation_lines(lessons)
    cite = ""
    if lines:
        cite = "; " + lines[0][:180]
    for opt in options or []:
        key = str(getattr(opt, "key", "") or "")
        if not key.startswith("buy:"):
            continue
        if option_delta:
            try:
                opt.score = max(0.05, float(opt.score) + option_delta)
            except (TypeError, ValueError, AttributeError):
                pass
            rationale = str(getattr(opt, "rationale", "") or "")
            opt.rationale = (
                rationale
                + ("; lesson caution" if option_delta < 0 else "; lesson support")
                + cite
            )
        refs = list(getattr(opt, "experience_refs", None) or [])
        for lid in ids:
            if lid not in refs:
                refs.append(lid)
        opt.experience_refs = refs
        try:
            opt.influence_events = list(events)
        except Exception:  # noqa: BLE001
            pass
    return options


def action_after_l0(
    action: str,
    *,
    research_gate: dict[str, Any] | None = None,
    portfolio_gate: dict[str, Any] | None = None,
    plc_a: dict[str, Any] | None = None,
    fundamentals: dict[str, Any] | None = None,
) -> str:
    """L0 wins. A lesson cannot authorize a buy that gates forbid."""
    act = str(action or "").strip().lower()
    if act != "buy":
        return act
    for g in (research_gate, portfolio_gate, plc_a):
        if not isinstance(g, dict):
            continue
        if g.get("allowed") is False:
            return "hold"
        state = str(g.get("state") or g.get("plc_a_state") or "").upper()
        if state == "INCOMPLETE":
            return "hold"
        reason = str(g.get("reason") or g.get("code") or "").lower()
        if "fundamentals_incomplete" in reason or "plc_a" in reason:
            return "hold"
    fund = fundamentals if isinstance(fundamentals, dict) else {}
    if fund and fund.get("pe") is None and fund.get("fcf") is None and fund.get("require_plc_a", True):
        # Explicit incomplete book used in Day-2: missing PE/FCF blocks buy.
        if fund.get("plc_a_required") or fund.get("block_if_incomplete"):
            return "hold"
    return act


def loop_closed_cite(packet: dict[str, Any] | None) -> bool:
    if not isinstance(packet, dict):
        return False
    refs = packet.get("experience_refs") or packet.get("lesson_refs")
    return bool(refs)


def experience_bias_map(
    symbols: list[str],
    lessons: list[dict[str, Any]] | None,
) -> dict[str, float]:
    """Same matcher → ranking experience_bias_by_symbol (not keyword scan)."""
    delta = l2_totals(lessons)["ranking"]
    if not delta:
        return {}
    out: dict[str, float] = {}
    for sym in symbols:
        s = str(sym or "").strip()
        if s:
            out[s] = delta
    return out
