"""CLC.R1 polarity — negative lesson must mean caution, not buy support.

Mechanical R1 (JSON → REVIEWED → persist) is green. This fixture asks whether
Atlas *understands* E001:

  Volume acceleration did not add … Do not treat vol-accel as a reason to buy.

Expected interpretation: ``caution``. Explicitly unacceptable: treating
vol-accel as supportive of a buy.

Deterministic L2 half (no LLM): matcher → negative polarity → bounded option
delta → buy score must not increase.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from atlas.investment.lesson_influence import (
    E001_LESSON_ID,
    E001_STATEMENT,
    OPTION_SCORE_CAP,
    RANKING_CAP,
    apply_to_options,
    canonical_e001_lesson,
    experience_bias_map,
    l2_totals,
    match_lessons,
    persist_canonical_e001_lesson,
)

VERSION = "clc.r1.polarity.v1"
LABORATORY_ID = "clc_r1_fixture"
POLARITY_ID = "clc-r1-synth-polarity-e001"
POLARITY_SYMBOL = "HBLPOWER.NS"
EXPECTED_INTERPRETATION = "caution"

_log = logging.getLogger("atlas.investment.clc_r1_polarity")

# Phrases that flip a negative validated lesson into buy support (fail).
# Avoid bare "reason to buy" — E001's statement says "Do not treat … as a
# reason to buy" (caution). Match supportive flips only.
SUPPORTIVE_FLIP = (
    "supports the buy",
    "support the buy",
    "supportive of a buy",
    "supportive of buy",
    "supports buying",
    "supports a buy",
    "volume acceleration supports",
    "vol-accel supports",
    "vol accel supports",
    "can support a buy",
    "can support buy",
    "positive for the buy",
    "bullish on volume acceleration",
    "buy recommendation is justified by volume",
)

_CAUTION_NEGATIONS = (
    "do not treat",
    "don't treat",
    "not to treat",
    "instructs not to treat",
    "do not use",
    "not a reason to buy",
    "never treat",
    "not treat vol",
    "not treat volume",
    "contradicts using volume acceleration as a support",
    "contradicts using vol-accel as a support",
)

CAUTION_TOKENS = (
    "caution",
    "cautionary",
    "negative",
    "do not treat",
    "not a reason to buy",
    "not treat vol",
    "bounded caution",
    "subtract",
    "ranking caution",
    "against buy",
)


@dataclass
class _BuyOpt:
    key: str
    score: float
    rationale: str = ""
    experience_refs: list[str] | None = None


def polarity_question() -> str:
    return (
        f"Lesson {E001_LESSON_ID}: {E001_STATEMENT} "
        "Atlas is evaluating a buy_name candidate that uses volume acceleration. "
        "Is this lesson supportive, neutral, or cautionary for the current "
        "candidate? Reply with interpretation exactly one of: "
        "supportive | neutral | caution. "
        "A negative validated lesson means caution (do not treat vol-accel as "
        "a reason to buy). Never invent a supportive reading. Advice-only. "
        "Never place orders."
    )


def polarity_packet() -> dict[str, Any]:
    return {
        "decision_id": POLARITY_ID,
        "symbol": POLARITY_SYMBOL,
        "action": "buy",
        "synthetic": True,
        "never_orders": True,
        "advice_only": True,
        "lesson_refs": [E001_LESSON_ID],
        "experience_refs": [E001_LESSON_ID],
        "no_match": False,
        "unknowns": ["plc_a_incomplete"],
        "observation_ids": ["obs-clc-r1-polarity"],
        "reasons_for": [polarity_question()],
        "belief_context": {"influence": "cited_bounded", "no_match": False},
        "polarity_test": True,
        "expected_interpretation": EXPECTED_INTERPRETATION,
    }


def retrieve_e001_for_buy() -> list[dict[str, Any]]:
    lesson = canonical_e001_lesson()
    cited = match_lessons(
        candidate={
            "decision_type": "buy_name",
            "action": "buy",
            "symbol": POLARITY_SYMBOL,
            "features": ["volume_acceleration_20d"],
            "query": "volume acceleration buy_name",
        },
        retrieved=[lesson],
        query="volume acceleration buy_name HBLPOWER",
    )
    return cited or [lesson]


def verify_l2_influence() -> dict[str, Any]:
    """Deterministic: E001 → negative L2 → buy score must not rise."""
    lessons = retrieve_e001_for_buy()
    totals = l2_totals(lessons)
    base = 0.72
    opts = [_BuyOpt(key=f"buy:{POLARITY_SYMBOL}", score=base, rationale="base")]
    apply_to_options(opts, lessons)
    after = float(opts[0].score)
    bias = experience_bias_map([POLARITY_SYMBOL], lessons)
    ids = [str(x.get("id") or "") for x in lessons if isinstance(x, dict)]
    sign = None
    for row in lessons:
        if isinstance(row, dict) and str(row.get("id") or "") == E001_LESSON_ID:
            sign = row.get("sign")
            break
    ok = bool(
        E001_LESSON_ID in ids
        and sign == -1
        and totals["option"] < 0
        and totals["option"] >= -OPTION_SCORE_CAP
        and after <= base
        and after < base  # must actually decrease for matching buy_name
        and (bias.get(POLARITY_SYMBOL) or 0) <= 0
    )
    return {
        "ok": ok,
        "lesson_id": E001_LESSON_ID,
        "sign": sign,
        "cited_ids": ids,
        "l2_option": totals["option"],
        "l2_ranking": totals["ranking"],
        "buy_score_before": base,
        "buy_score_after": after,
        "buy_score_increased": after > base,
        "experience_bias": bias.get(POLARITY_SYMBOL),
        "caps": {"option": OPTION_SCORE_CAP, "ranking": RANKING_CAP},
        "honesty": (
            "L2 influence is deterministic. Qwen text cannot raise the buy "
            "option score; a negative validated lesson only subtracts within caps."
        ),
    }


def text_claims_supportive(text: str) -> bool:
    blob = " ".join(str(text or "").lower().replace("_", " ").split())
    # When the text is clearly stating the E001 caution, do not flag it as a flip
    # merely because it quotes "reason to buy" or "support for the buy" in negation.
    if any(neg in blob for neg in _CAUTION_NEGATIONS):
        return any(tok in blob for tok in SUPPORTIVE_FLIP)
    if any(tok in blob for tok in SUPPORTIVE_FLIP):
        return True
    if "reason to buy" in blob:
        return True
    return False


def text_claims_caution(text: str) -> bool:
    blob = " ".join(str(text or "").lower().replace("_", " ").split())
    return any(tok in blob for tok in CAUTION_TOKENS)


def normalize_interpretation(raw: Any) -> str | None:
    s = str(raw or "").strip().lower()
    if not s:
        return None
    if s in {"caution", "cautionary", "negative", "against"}:
        return "caution"
    if s in {"supportive", "support", "positive", "for"}:
        return "supportive"
    if s in {"neutral", "none", "n/a"}:
        return "neutral"
    if "caution" in s or "negative" in s:
        return "caution"
    if "support" in s or "positive" in s:
        return "supportive"
    if "neutral" in s:
        return "neutral"
    return None


def score_polarity_advice(advice: dict[str, Any] | None) -> dict[str, Any]:
    """Score an LLM polarity answer. Fail on supportive flip of E001."""
    doc = advice if isinstance(advice, dict) else {}
    interpretation = normalize_interpretation(
        doc.get("interpretation") or doc.get("polarity")
    )
    rationale = str(doc.get("rationale") or doc.get("rationale_text") or "")
    cited = [str(x) for x in (doc.get("cited_ids") or doc.get("lesson_refs") or []) if x]
    if not cited and E001_LESSON_ID in rationale:
        cited = [E001_LESSON_ID]
    flip = text_claims_supportive(rationale) or interpretation == "supportive"
    caution_ok = interpretation == "caution" or (
        interpretation is None and text_claims_caution(rationale) and not flip
    )
    reviewed = str(doc.get("review_status") or "") == "REVIEWED"
    ok = bool(
        reviewed
        and caution_ok
        and not flip
        and E001_LESSON_ID in cited
        and rationale.strip()
        and len(rationale.strip()) >= 40
    )
    return {
        "ok": ok,
        "lesson_id": E001_LESSON_ID,
        "interpretation": interpretation or ("caution" if caution_ok else None),
        "expected": EXPECTED_INTERPRETATION,
        "cited_ids": cited,
        "flip_supportive": flip,
        "review_status": doc.get("review_status"),
        "rationale_preview": rationale[:200],
        "confidence": doc.get("confidence"),
        "falsifiers": list(doc.get("falsifiers") or [])[:6],
        "never_orders": True,
    }


def _render_polarity_prompt() -> str:
    return "\n".join(
        [
            "Reply with ONLY a JSON object. First character '{'. Do not copy instructions.",
            "Keys: lesson_id, interpretation (supportive|neutral|caution), rationale,",
            "falsifiers (list), cited_ids (list), confidence (0-1).",
            f"lesson_id must be {E001_LESSON_ID}.",
            f"Lesson statement: {E001_STATEMENT}",
            polarity_question(),
            "Unacceptable: claiming volume acceleration supports the buy.",
            "Never place orders.",
        ]
    )


def reason_polarity(*, llm: Any) -> dict[str, Any]:
    """Ask Qwen for E001 polarity. Fail-open to UNREVIEWED on bad contract."""
    from atlas.llm.provider import ChatMessage
    from atlas.reasoning.cognitive_core import (
        REVIEWED,
        UNREVIEWED,
        _is_prompt_echo,
        _is_schema_echo,
        _parse_json_blob,
        _clip,
        _str_list,
    )

    if llm is None:
        return {
            "review_status": UNREVIEWED,
            "skip_reason": "no_llm",
            "lesson_id": E001_LESSON_ID,
        }
    try:
        if hasattr(llm, "lane_busy") and llm.lane_busy():
            return {
                "review_status": UNREVIEWED,
                "skip_reason": "lane_busy",
                "lesson_id": E001_LESSON_ID,
            }
    except Exception:  # noqa: BLE001
        pass

    client = llm
    if hasattr(llm, "for_role"):
        try:
            client = llm.for_role("market")
        except Exception:  # noqa: BLE001
            try:
                client = llm.for_role("scientist")
            except Exception:  # noqa: BLE001
                client = llm

    messages = [
        ChatMessage(
            role="system",
            content=(
                "You are Atlas's lesson-polarity checker (advice-only). "
                "Negative validated lessons mean caution, never buy support. "
                "Output only the JSON object. Never place orders."
            ),
        ),
        ChatMessage(role="user", content=_render_polarity_prompt()),
    ]
    chat_kw: dict[str, Any] = {
        "_atlas_purpose": "clc_r1_polarity",
        "think": False,
        "num_predict": 350,
        "format": "json",
        "temperature": 0.0,
        "timeout": 300.0,
    }
    try:
        resp = client.chat(messages, **chat_kw)
        text = getattr(resp, "text", None) or getattr(resp, "content", None) or ""
    except Exception as exc:  # noqa: BLE001
        return {
            "review_status": UNREVIEWED,
            "skip_reason": f"failed:{type(exc).__name__}",
            "lesson_id": E001_LESSON_ID,
            "llm": True,
        }

    raw = str(text or "")[:2000]
    parsed = _parse_json_blob(raw)
    if _is_prompt_echo(parsed) or _is_schema_echo(parsed):
        return {
            "review_status": UNREVIEWED,
            "skip_reason": "failed_schema_echo",
            "lesson_id": E001_LESSON_ID,
            "llm": True,
            "raw_llm_text": raw,
        }
    if not parsed:
        return {
            "review_status": UNREVIEWED,
            "skip_reason": "failed_non_json",
            "lesson_id": E001_LESSON_ID,
            "llm": True,
            "raw_llm_text": raw,
        }

    interpretation = normalize_interpretation(parsed.get("interpretation"))
    rationale = _clip(parsed.get("rationale") or parsed.get("rationale_text"), 1200).strip()
    falsifiers = _str_list(parsed.get("falsifiers"), 8, 200)
    cited = [str(x) for x in (parsed.get("cited_ids") or []) if x][:8]
    if E001_LESSON_ID not in cited:
        cited = [E001_LESSON_ID, *cited]
    conf = parsed.get("confidence")
    try:
        conf_f = float(conf) if conf is not None and conf != "" else None
        if conf_f is not None:
            conf_f = max(0.0, min(1.0, conf_f))
    except (TypeError, ValueError):
        conf_f = None

    flip = text_claims_supportive(rationale) or interpretation == "supportive"
    if flip:
        return {
            "version": VERSION,
            "review_status": UNREVIEWED,
            "skip_reason": "failed_polarity_inversion",
            "lesson_id": E001_LESSON_ID,
            "interpretation": interpretation,
            "rationale": rationale or None,
            "falsifiers": falsifiers,
            "cited_ids": cited,
            "confidence": conf_f,
            "llm": True,
            "raw_llm_text": raw,
            "honesty": (
                "E001 is a negative lesson. Supportive readings are rejected; "
                "REVIEWED requires interpretation=caution."
            ),
        }
    if interpretation != "caution" and not text_claims_caution(rationale):
        return {
            "version": VERSION,
            "review_status": UNREVIEWED,
            "skip_reason": "failed_polarity_not_caution",
            "lesson_id": E001_LESSON_ID,
            "interpretation": interpretation,
            "rationale": rationale or None,
            "falsifiers": falsifiers,
            "cited_ids": cited,
            "confidence": conf_f,
            "llm": True,
            "raw_llm_text": raw,
        }
    if not rationale or len(rationale) < 40:
        return {
            "version": VERSION,
            "review_status": UNREVIEWED,
            "skip_reason": "empty_rationale",
            "lesson_id": E001_LESSON_ID,
            "llm": True,
            "raw_llm_text": raw,
        }

    return {
        "version": VERSION,
        "kind": "CLC_R1_POLARITY",
        "review_status": REVIEWED,
        "llm": True,
        "lesson_id": E001_LESSON_ID,
        "interpretation": "caution",
        "rationale": rationale,
        "rationale_text": rationale,
        "falsifiers": falsifiers,
        "cited_ids": cited,
        "confidence": conf_f,
        "raw_llm_text": raw,
        "never_orders": True,
        "honesty": (
            "Polarity REVIEWED: E001 read as caution. Not R1-LIVE. Not L5."
        ),
    }


def persist_polarity(
    data_dir: str | Path,
    advice: dict[str, Any],
) -> Path:
    root = Path(data_dir) / "investment" / "decide_rationale" / LABORATORY_ID / "by_id"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{POLARITY_ID}.json"
    row = {
        "version": VERSION,
        "decision_id": POLARITY_ID,
        "laboratory_id": LABORATORY_ID,
        "symbol": POLARITY_SYMBOL,
        "action": "buy",
        "synthetic": True,
        "never_orders": True,
        "advice_only": True,
        "polarity_test": True,
        "status": "done" if advice.get("review_status") == "REVIEWED" else "failed",
        "lesson_refs": [E001_LESSON_ID],
        "experience_refs": [E001_LESSON_ID],
        **advice,
        "packet_summary": {
            "synthetic": True,
            "lesson_refs": [E001_LESSON_ID],
            "no_match": False,
            "expected_interpretation": EXPECTED_INTERPRETATION,
        },
    }
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(row, indent=2, default=str) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def run_polarity_fixture(
    data_dir: str | Path,
    *,
    llm: Any | None = None,
    skip_llm: bool = False,
) -> dict[str, Any]:
    """L2 influence always; optional live/FakeLLM polarity."""
    persist_canonical_e001_lesson(data_dir)
    l2 = verify_l2_influence()
    report: dict[str, Any] = {
        "version": VERSION,
        "kind": "CLC_R1_POLARITY",
        "r1_live": False,
        "never_orders": True,
        "sma_rsi_untouched": True,
        "laboratory_id": LABORATORY_ID,
        "l2": l2,
        "honesty": (
            "Semantic polarity of E001 + deterministic L2. "
            "Mechanical R1-SYNTHETIC green ≠ grounded reasoning. Not L5."
        ),
    }
    if skip_llm or llm is None:
        report["polarity"] = {
            "skipped": True,
            "reason": "llm_not_requested",
            "ok": False,
        }
        report["semantic_green"] = False
        report["l2_green"] = bool(l2.get("ok"))
        report["polarity_green"] = bool(l2.get("ok")) and False
        return report

    advice = reason_polarity(llm=llm)
    path = persist_polarity(data_dir, advice)
    scored = score_polarity_advice(advice)
    report["polarity"] = {**scored, "path": str(path), "skip_reason": advice.get("skip_reason")}
    report["l2_green"] = bool(l2.get("ok"))
    report["semantic_green"] = bool(scored.get("ok"))
    report["polarity_green"] = bool(l2.get("ok") and scored.get("ok"))
    return report


def e001_polarity_inverted_in_decide_text(text: str, *, lesson_refs: list[Any] | None = None) -> bool:
    """True when a decide-rationale claims E001 supports buying.

    Thin wrapper — implementation is lesson.expected_effect (COG-2).
    E001 remains the regression fixture, not the mechanism owner.
    """
    from atlas.reasoning.cognitive_contract import polarity_inverted_vs_expected_effect

    lessons: list[dict[str, Any]] = []
    refs = list(lesson_refs or [])
    for ref in refs:
        rid = str(ref.get("id") if isinstance(ref, dict) else ref)
        if rid == E001_LESSON_ID or "E001" in rid or "vol-accel" in rid.lower():
            lessons.append(canonical_e001_lesson())
        elif isinstance(ref, dict):
            lessons.append(ref)
        elif rid:
            lessons.append({"id": rid})
    if not lessons:
        # No refs — still check blob for E001 mention via canonical lesson.
        blob = " ".join(str(text or "").lower().replace("_", " ").split())
        if (
            "e001" in blob
            or "vol-accel" in blob
            or "volume accel" in blob
            or "l-e001" in blob
        ):
            lessons = [canonical_e001_lesson()]
            refs = [E001_LESSON_ID]
        else:
            return False
    return polarity_inverted_vs_expected_effect(
        text, lessons=lessons, lesson_refs=refs or [E001_LESSON_ID]
    )


def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="CLC.R1 polarity + L2 influence (no orders)")
    parser.add_argument("--data-dir", default="")
    parser.add_argument("--live", action="store_true", help="Call local qwen3:4b")
    parser.add_argument("--l2-only", action="store_true", help="Skip LLM; L2 only")
    args = parser.parse_args(argv)
    data_dir = args.data_dir
    if not data_dir:
        from atlas.config import get_config

        data_dir = str(get_config().paths.data)
    if args.l2_only:
        report = run_polarity_fixture(data_dir, llm=None, skip_llm=True)
        print(json.dumps(report, indent=2, default=str))
        return 0 if report.get("l2_green") else 1
    if not args.live:
        print("pass --live or --l2-only", file=sys.stderr)
        return 2
    from atlas.investment.clc_r1_fixture import live_llm

    report = run_polarity_fixture(data_dir, llm=live_llm())
    print(json.dumps(report, indent=2, default=str))
    return 0 if report.get("polarity_green") else 1


if __name__ == "__main__":
    raise SystemExit(main())
