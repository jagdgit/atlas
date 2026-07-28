"""ARMF Phase A — operator glossary for Ops states and capacity concepts."""

from __future__ import annotations

from typing import Any

# Plain-language definitions for the Operations dashboard (A1).
OPS_GLOSSARY: list[dict[str, str]] = [
    {
        "id": "starved",
        "term": "Starved",
        "definition": (
            "No productive tick for ≥6 hours while the worker is still eligible/running. "
            "Not a crash — often zombies (e.g. hello_watcher) or work blocked by budget/Host Guard."
        ),
    },
    {
        "id": "at_risk",
        "term": "At risk",
        "definition": (
            "Eligible worker has gone ≥30 minutes (or ≥30× expected tick) without a productive tick, "
            "but not yet the 6h Starved threshold. Intervene before the scarlet letter."
        ),
    },
    {
        "id": "waiting_host",
        "term": "Waiting Host",
        "definition": (
            "Admitted work deferred by Host Guard, tick budget, capacity queue, or archive lane — "
            "not operator pause."
        ),
    },
    {
        "id": "inventory_vs_ticks",
        "term": "Inventory vs tick slots",
        "definition": (
            "Workers (inventory) = how many persistent worker identities exist. "
            "Tick slots = how many are allowed to run a tick right now (real concurrency)."
        ),
    },
    {
        "id": "program_shares",
        "term": "Program shares",
        "definition": (
            "Reserved capacity % per program (Market / Engineering / Personal / …) with borrowing "
            "when idle. Host Guard remains the final machine-safety veto."
        ),
    },
    {
        "id": "research_velocity",
        "term": "Research Velocity",
        "definition": (
            "Knowledge produced today (e.g. dossiers advanced / day) — not CPU%, worker count, or ticks. "
            "Primary question: did Atlas produce more knowledge today?"
        ),
    },
]


def glossary_snapshot() -> dict[str, Any]:
    return {
        "version": "armf.a1",
        "entries": list(OPS_GLOSSARY),
    }
