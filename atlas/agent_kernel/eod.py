"""Evening digest section for autonomous work.

Reads the kernel state file. Omits itself when Atlas has no kernel state yet,
so unrelated evening reports stay unchanged.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_kernel_state(data_dir: str | Path | None) -> dict[str, Any] | None:
    if not data_dir:
        return None
    path = Path(data_dir) / "agent_kernel" / "state.json"
    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return doc if isinstance(doc, dict) else None


def format_autonomous_agent_lines(data_dir: str | Path | None) -> list[str]:
    state = load_kernel_state(data_dir)
    if not state:
        return []
    tasks = list((state.get("tasks") or {}).values())
    done = [t for t in tasks if t.get("status") == "SUCCESS"]
    gaps = list(state.get("capability_gaps") or [])
    failed = [
        t
        for t in tasks
        if t.get("status")
        in {"CAPABILITY_GAP", "FAILED", "PLANNING_FAILED", "BLOCKED", "UNVERIFIED"}
    ]
    waiting = [
        t
        for t in tasks
        if t.get("status") in {"WAITING_FOR_EVENT", "RETRY_SCHEDULED", "DEFERRED", "PARTIAL"}
    ]
    experiences = list(state.get("experiences") or [])
    hypotheses = [h for h in (state.get("active_hypotheses") or []) if h]
    lines = [
        "",
        "━━━━━━━━ AUTONOMOUS AGENT ━━━━━━━━",
        f"Current objective: {state.get('current_goal') or '(none)'}",
        f"Completed autonomous tasks: {len(done)}",
    ]
    for row in done[:5]:
        lines.append(f"  - {row.get('symbol') or ''} {row.get('objective')}")
    lines.append(f"Investigations: {len(state.get('episodes') or [])}")
    lines.append(f"Successful resolutions: {len(state.get('recent_successes') or [])}")
    lines.append(f"Failed investigations: {len(failed)}")
    for row in failed[:5]:
        lines.append(
            f"  - {row.get('status')} {row.get('symbol') or ''}: {row.get('reason')}"
        )
    lines.append(f"Capability gaps: {len(gaps)}")
    for gap in gaps[:5]:
        lines.append(
            f"  - missing {gap.get('missing')} next {gap.get('next_action')} "
            f"retry {gap.get('retry')}"
        )
    lines.append(f"New hypotheses: {len(hypotheses)}")
    for item in hypotheses[:3]:
        lines.append(f"  - {item}")
    lines.append(f"Experiences created: {len(experiences)}")
    lines.append("Lessons proposed: provisional only (not validated)")
    lines.append(f"Waiting for: {len(waiting)}")
    for row in waiting[:5]:
        lines.append(f"  - {row.get('status')} {row.get('next_action')}")
    nxt = (state.get("next_actions") or [None])[0]
    if isinstance(nxt, dict):
        lines.append(
            f"Next autonomous action: {nxt.get('next_action')} "
            f"({nxt.get('status')})"
        )
    else:
        lines.append("Next autonomous action: (none scheduled)")
    return lines
