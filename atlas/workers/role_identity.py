"""Worker-tick role identity — keep independent labs from collapsing.

Phase 5 (2026-10-08) paused the F&O paper worker because it shared
``(program_id, worker_type)`` with the Intraday paper worker. Independent
paper labs must include ``laboratory_id`` (portfolio_key) in the role key.

Real program-reconcile duplicates (same triple) still collapse to one ACTIVE.
"""

from __future__ import annotations

from typing import Any, Iterable

PAPER_TRADING = "paper_trading"

ACTIVE = "ACTIVE"
STALE = "STALE"

# Labs that must never share a single enabled paper_trading tick.
KNOWN_PAPER_LABS = frozenset(
    {
        "india_fno_learner",
        "equity_intraday_learner",
        "india_equity_learner",
    }
)


def laboratory_id_from_row(row: dict[str, Any] | None) -> str:
    """Extract laboratory / portfolio key from a worker / mission classification row."""
    if not isinstance(row, dict):
        return ""
    worker_type = str(row.get("worker_type") or row.get("type") or "").strip()
    if worker_type != PAPER_TRADING:
        return ""
    for key in ("laboratory_id", "portfolio_key", "lab_id"):
        val = row.get(key)
        if val:
            return str(val).strip()
    for nest_name in ("config", "metadata", "mission_metadata", "checkpoint"):
        nest = row.get(nest_name)
        if not isinstance(nest, dict):
            continue
        for key in ("portfolio_key", "laboratory_id", "lab_id"):
            val = nest.get(key)
            if val:
                return str(val).strip()
        doc = nest.get("document")
        if isinstance(doc, dict):
            for key in ("portfolio_key", "laboratory_id"):
                val = doc.get(key)
                if val:
                    return str(val).strip()
    return ""


def role_key(
    program_id: str | None,
    worker_type: str | None,
    laboratory_id: str | None = None,
) -> tuple[str, str, str]:
    """Durable role identity for worker_tick dedupe.

    ``laboratory_id`` is required for ``paper_trading`` so F&O / Intraday / Swing
    under the same program stay distinct. Other worker types keep an empty lab.
    """
    prog = str(program_id or "_unscoped").strip() or "_unscoped"
    wtype = str(worker_type or "").strip()
    lab = ""
    if wtype == PAPER_TRADING:
        lab = str(laboratory_id or "").strip()
    return (prog, wtype, lab)


def role_key_from_row(row: dict[str, Any]) -> tuple[str, str, str]:
    return role_key(
        row.get("program_id"),
        row.get("worker_type") or row.get("type"),
        laboratory_id_from_row(row),
    )


def _keep_score(row: dict[str, Any]) -> tuple:
    """Prefer older mission, then most recent tick — same intent as Phase 5."""
    mission_created = str(row.get("mission_created_at") or "")
    last_tick = str(row.get("last_tick_at") or row.get("last_run_at") or "")
    # Ascending mission_created (older first), descending last_tick via inversion
    return (mission_created, "" if not last_tick else last_tick)


def classify_worker_tick_roles(
    rows: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Classify enabled worker_tick rows as ACTIVE or STALE by role_key.

    Within each role_key, keep exactly one ACTIVE (oldest mission's best ticker).
    Distinct laboratory_ids under paper_trading never share a key.
    """
    items: list[dict[str, Any]] = []
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        row = dict(raw)
        key = role_key_from_row(row)
        row["_role_key"] = key
        row["laboratory_id"] = key[2]
        items.append(row)

    by_key: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in items:
        by_key.setdefault(row["_role_key"], []).append(row)

    out: list[dict[str, Any]] = []
    for key, group in by_key.items():
        ranked = sorted(group, key=_keep_score)
        keeper = ranked[0]
        for i, row in enumerate(ranked):
            result = {k: v for k, v in row.items() if not str(k).startswith("_")}
            result["role_key"] = {
                "program_id": key[0],
                "worker_type": key[1],
                "laboratory_id": key[2],
            }
            if i == 0:
                result["classification"] = ACTIVE
                result["reason"] = (
                    f"canonical for {key[0]}/{key[1]}"
                    + (f"/{key[2]}" if key[2] else "")
                    + " (kept)"
                )
            else:
                result["classification"] = STALE
                result["reason"] = (
                    f"duplicate role {key[0]}/{key[1]}"
                    + (f"/{key[2]}" if key[2] else "")
                    + f"; keep schedule={keeper.get('schedule_id')} "
                    f"worker={keeper.get('worker_id')} "
                    f"mission={keeper.get('mission_id')}"
                )
            out.append(result)
    return out


def assert_known_paper_labs_survive(classified: list[dict[str, Any]]) -> list[str]:
    """Return laboratory_ids among KNOWN_PAPER_LABS that were marked STALE — should be empty."""
    bad: list[str] = []
    for row in classified:
        lab = str((row.get("role_key") or {}).get("laboratory_id") or row.get("laboratory_id") or "")
        if lab in KNOWN_PAPER_LABS and row.get("classification") == STALE:
            bad.append(lab)
    return bad
