"""CLC.R1-SYNTHETIC — controlled decide-rationale fixture (no orders).

Two packets in laboratory ``clc_r1_fixture``:

* cite: HBLPOWER + retrieved E001 volume-acceleration lesson
* no_match: honest empty retrieval — must not invent a lesson

Does not place BUY/SELL. Does not mutate SMA/RSI. Does not close R1-LIVE.
R1-SYNTHETIC green ≠ Atlas has learned / L5.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from atlas.investment.decide_rationale import (
    drain_pending_rationales,
    load_rationale,
    schedule_decide_rationale,
)
from atlas.investment.lesson_influence import (
    E001_LESSON_ID,
    E001_STATEMENT,
    canonical_e001_lesson,
    match_lessons,
    persist_canonical_e001_lesson,
)
from atlas.llm.fitness_ledger import day_path, ist_today

VERSION = "clc.r1.synthetic.v1"
LABORATORY_ID = "clc_r1_fixture"
CITE_ID = "clc-r1-synth-cite-e001"
NOMATCH_ID = "clc-r1-synth-nomatch"
CITE_SYMBOL = "HBLPOWER.NS"
NOMATCH_SYMBOL = "FIXTURE.NS"

_log = logging.getLogger("atlas.investment.clc_r1_fixture")

CITE_QUESTION = (
    "Suppose Atlas is evaluating HBLPOWER and retrieves the existing "
    "volume-acceleration lesson. Explain whether that lesson is relevant "
    "to this decision, what would falsify its application, and whether it "
    "should change ranking/caution within the bounded L2 limit. Advice-only. "
    "Never place orders or recommend sizes."
)


def retrieve_e001() -> list[dict[str, Any]]:
    lesson = canonical_e001_lesson()
    cited = match_lessons(
        candidate={
            "decision_type": "buy_name",
            "action": "buy",
            "symbol": CITE_SYMBOL,
            "features": ["volume_acceleration_20d"],
            "query": "Does volume acceleration help buy_name?",
        },
        retrieved=[lesson],
        query="volume acceleration buy_name HBLPOWER",
    )
    return cited or [lesson]


def cite_packet() -> dict[str, Any]:
    cited = retrieve_e001()
    ids = [str(x.get("id") or "") for x in cited if isinstance(x, dict) and x.get("id")]
    if E001_LESSON_ID not in ids:
        ids = [E001_LESSON_ID, *ids]
    return {
        "decision_id": CITE_ID,
        "symbol": CITE_SYMBOL,
        "action": "buy",
        "synthetic": True,
        "never_orders": True,
        "advice_only": True,
        "lesson_refs": ids[:8],
        "experience_refs": ids[:8],
        "no_match": False,
        "unknowns": ["plc_a_incomplete", "fcf"],
        "observation_ids": ["obs-clc-r1-synth-cite"],
        "reasons_for": [
            CITE_QUESTION,
            E001_STATEMENT[:240],
        ],
        "belief_context": {"influence": "cited_bounded", "no_match": False},
    }


def nomatch_packet() -> dict[str, Any]:
    return {
        "decision_id": NOMATCH_ID,
        "symbol": NOMATCH_SYMBOL,
        "action": "buy",
        "synthetic": True,
        "never_orders": True,
        "advice_only": True,
        "lesson_refs": [],
        "experience_refs": [],
        "no_match": True,
        "unknowns": ["no_matching_lesson", "fundamentals"],
        "observation_ids": ["obs-clc-r1-synth-nomatch"],
        "reasons_for": [
            "Synthetic fixture: no retrieved lesson. Honest no_match. "
            "Do not invent E001 or any other lesson. Advice-only. Never orders."
        ],
        "belief_context": {"influence": "advice_only", "no_match": True},
    }


def reset_fixture(data_dir: str | Path) -> int:
    """Unlink prior fixture sidecars so a retry can re-drain. Never touches other labs."""
    from atlas.investment.decide_rationale import _by_id_dir, _safe

    root = _by_id_dir(data_dir, LABORATORY_ID)
    n = 0
    for did in (CITE_ID, NOMATCH_ID):
        path = root / f"{_safe(did)}.json"
        if path.is_file():
            path.unlink()
            n += 1
    return n


def schedule_both(data_dir: str | Path, *, force: bool = False) -> dict[str, Any]:
    persist_canonical_e001_lesson(data_dir)
    if force:
        reset_fixture(data_dir)
    cite = schedule_decide_rationale(
        data_dir,
        decision_id=CITE_ID,
        symbol=CITE_SYMBOL,
        action="buy",
        laboratory_id=LABORATORY_ID,
        packet=cite_packet(),
    )
    nomatch = schedule_decide_rationale(
        data_dir,
        decision_id=NOMATCH_ID,
        symbol=NOMATCH_SYMBOL,
        action="buy",
        laboratory_id=LABORATORY_ID,
        packet=nomatch_packet(),
    )
    return {"cite": cite, "nomatch": nomatch, "never_orders": True}


def run_fixture(
    data_dir: str | Path,
    *,
    llm: Any,
    max_passes: int = 2,
    force: bool = False,
) -> dict[str, Any]:
    """Schedule both packets and drain once. Never places orders."""
    scheduled = schedule_both(data_dir, force=force)
    drain = drain_pending_rationales(
        data_dir,
        laboratory_id=LABORATORY_ID,
        llm=llm,
        max_passes=max_passes,
        limit=8,
    )
    cite_row = load_rationale(data_dir, CITE_ID, laboratory_id=LABORATORY_ID)
    nomatch_row = load_rationale(data_dir, NOMATCH_ID, laboratory_id=LABORATORY_ID)
    report = {
        "version": VERSION,
        "kind": "CLC_R1_SYNTHETIC",
        "r1_live": False,
        "never_orders": True,
        "sma_rsi_untouched": True,
        "laboratory_id": LABORATORY_ID,
        "drain": {
            "done": drain.get("done"),
            "failed": drain.get("failed"),
            "pending": drain.get("pending"),
            "r1_quota_expired": drain.get("r1_quota_expired"),
        },
        "cite": _score_cite(cite_row),
        "nomatch": _score_nomatch(nomatch_row),
        "honesty": (
            "R1-SYNTHETIC proves the structured reasoning path. "
            "It does not prove R1-LIVE or L5."
        ),
    }
    report["fitness"] = fitness_bre3_rows(data_dir)
    report["synthetic_green"] = bool(
        report["cite"].get("ok") and report["nomatch"].get("ok")
    )
    report["scheduled"] = {
        "cite_id": (scheduled.get("cite") or {}).get("decision_id"),
        "nomatch_id": (scheduled.get("nomatch") or {}).get("decision_id"),
    }
    return report


def fitness_bre3_rows(data_dir: str | Path | None) -> dict[str, Any]:
    path = day_path(data_dir)
    rows: list[dict[str, Any]] = []
    if path is not None and path.is_file():
        try:
            tail = path.read_text(encoding="utf-8").splitlines()[-800:]
        except OSError:
            tail = []
        for line in tail:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict) and row.get("purpose") == "bre3_decide_rationale":
                rows.append(row)
    return {
        "as_of_ist": ist_today(),
        "count": len(rows),
        "ok_count": sum(1 for r in rows if r.get("outcome") == "ok"),
        "ids": [str(r.get("inference_id") or "") for r in rows[-4:]],
    }


def _placeholder_rationale(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t or t in {"1-3 sentences", "str", "string"}:
        return True
    return len(t) < 40


def _score_cite(row: dict[str, Any] | None) -> dict[str, Any]:
    doc = row if isinstance(row, dict) else {}
    text = str(doc.get("rationale_text") or "")
    blob = text.lower() + " " + json.dumps(doc.get("claims") or []).lower()
    cited = E001_LESSON_ID.lower() in blob or "e001" in blob or "volume accel" in blob
    reviewed = str(doc.get("review_status") or "") == "REVIEWED"
    done = str(doc.get("status") or "") == "done"
    placeholder = _placeholder_rationale(text)
    return {
        "ok": bool(done and reviewed and doc.get("llm") and cited and not placeholder),
        "status": doc.get("status"),
        "review_status": doc.get("review_status"),
        "llm": bool(doc.get("llm")),
        "cited_e001": cited,
        "placeholder": placeholder,
        "skip_reason": doc.get("skip_reason"),
        "rationale_preview": text[:180],
        "never_orders": True,
    }


def _score_nomatch(row: dict[str, Any] | None) -> dict[str, Any]:
    doc = row if isinstance(row, dict) else {}
    text = str(doc.get("rationale_text") or "")
    blob = text.lower()
    invented = (
        "l-e001-buy_name-vol-accel" in blob
        or "volume acceleration did not add" in blob
    )
    reviewed = str(doc.get("review_status") or "") == "REVIEWED"
    done = str(doc.get("status") or "") == "done"
    honest = bool(doc.get("no_match") is True or (doc.get("packet_summary") or {}).get("no_match") is True)
    placeholder = _placeholder_rationale(text)
    return {
        "ok": bool(
            done
            and reviewed
            and doc.get("llm")
            and honest
            and not invented
            and not placeholder
        ),
        "status": doc.get("status"),
        "review_status": doc.get("review_status"),
        "llm": bool(doc.get("llm")),
        "honest_no_match": honest,
        "invented_e001": invented,
        "placeholder": placeholder,
        "skip_reason": doc.get("skip_reason"),
        "rationale_preview": text[:180],
        "never_orders": True,
    }


def live_llm() -> Any:
    """One local reasoner (qwen3:4b). Fitness rows go to configured data_dir."""
    from atlas.llm.ollama_provider import OllamaProvider
    from atlas.llm.service import LLMService

    provider = OllamaProvider(
        model="qwen3:4b",
        embedding_model="nomic-embed-text",
        timeout=300.0,
        think=False,
    )
    return LLMService(
        provider,
        model="qwen3:4b",
        embedding_model="nomic-embed-text",
        roles={
            "chat": "qwen3:4b",
            "market": "qwen3:4b",
            "scientist": "qwen3:4b",
            "planner": "qwen3:4b",
            "embed": "nomic-embed-text",
        },
    )


def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="CLC.R1-SYNTHETIC fixture (no orders)")
    parser.add_argument(
        "--data-dir",
        default="",
        help="Atlas data dir (default: config paths.data)",
    )
    parser.add_argument("--live", action="store_true", help="Call local qwen3:4b")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace prior fixture sidecars and re-drain (this lab only)",
    )
    parser.add_argument(
        "--also-j1",
        action="store_true",
        help="If synthetic_green, enqueue CLC.J1 (E001 investigation; no SMA/RSI)",
    )
    args = parser.parse_args(argv)
    data_dir = args.data_dir
    if not data_dir:
        from atlas.config import get_config

        data_dir = str(get_config().paths.data)
    if not args.live:
        print("pass --live to call qwen3:4b; hermetic tests cover FakeLLM", file=sys.stderr)
        return 2
    report = run_fixture(data_dir, llm=live_llm(), max_passes=2, force=args.force)
    if args.also_j1 and report.get("synthetic_green"):
        from atlas.investment.clc_j1 import start_j1

        report["j1"] = start_j1()
        report["j1_note"] = (
            "J1 enqueued after R1-SYNTHETIC REVIEWED. This is not R1-LIVE and not L5."
        )
    elif args.also_j1:
        report["j1"] = {"started": False, "reason": "synthetic_not_green"}
    print(json.dumps(report, indent=2, default=str))
    return 0 if report.get("synthetic_green") else 1


if __name__ == "__main__":
    raise SystemExit(main())
