"""OI-CHAT-INFER0 Stages 4–5 — experiment / learning loop status (first slice).

Does not invent a parallel experiment system. Surfaces CU.B / LINT0 learning-story
counts so evening mail shows hypothesis → prediction → outcome → attribution health.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

VERSION = "chat_infer0.cognitive_loop.v1"


def format_cognitive_loop_evening_lines(
    data_dir: str | Path | None,
    *,
    as_of_ist: str | None = None,
    lab_ids: list[str] | None = None,
) -> list[str]:
    """Stage 4–5 evening: prediction/outcome/attribution from learning stories."""
    lines = [
        "",
        "── Cognitive loop (OI-CHAT-INFER0 Stages 4–5) ──",
        "  Contract: hypothesis → prediction → test → outcome → attribution → candidate",
    ]
    if not data_dir:
        lines.append("  (no data_dir — loop status unavailable)")
        return lines

    labs = lab_ids or [
        "india_equity_learner",
        "india_fno_learner",
        "equity_intraday_learner",
    ]
    try:
        from atlas.investment.learning_objects import ist_today, load_learning_events
        from atlas.investment.learning_story import summarize_learning_stories

        day = as_of_ist or ist_today()
    except Exception:  # noqa: BLE001
        lines.append("  (learning modules unavailable)")
        return lines

    total = pred_absent = unk_cause = 0
    for lab in labs:
        try:
            events = load_learning_events(data_dir, laboratory_id=lab, as_of_ist=day)
        except Exception:  # noqa: BLE001
            events = []
        summary = summarize_learning_stories(events)
        n = int(summary.get("stories") or 0)
        total += n
        pred_absent += int(summary.get("prediction_absent") or 0)
        unk_cause += int(summary.get("unknown_explicit_cause") or 0)
        lines.append(
            f"  · {lab}: stories={n} · prediction_absent={summary.get('prediction_absent', 0)} · "
            f"unknown_cause={summary.get('unknown_explicit_cause', 0)}"
        )

    lines.append(
        f"  rollup: stories={total} · prediction_absent={pred_absent} · "
        f"unknown_explicit_cause={unk_cause}"
    )
    lines.append(
        "  Stage 5 learning = prediction error + attribution → candidate for future test. "
        "No vanity story without a qualifying close. (CU.B / LINT0)"
    )
    lines.append(f"  version={VERSION}")
    return lines
