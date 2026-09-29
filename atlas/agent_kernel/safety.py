"""Hard boundaries for autonomous work.

LLM text and planned steps cannot place orders, change strategy control,
promote validated lessons, or declare evidence true.
"""

from __future__ import annotations

from typing import Any

FORBIDDEN_CAPABILITIES = frozenset(
    {
        "place_order",
        "submit_order",
        "live_order",
        "broker_order",
        "alter_strategy",
        "alter_strategy_control",
        "promote_lesson",
        "promote_validated_lesson",
        "declare_truth",
        "declare_evidence_truth",
        "bypass_gate",
        "bypass_plc",
    }
)

ORDER_ACTIONS = frozenset({"BUY", "SELL", "ORDER", "PLACE_ORDER", "LIVE_ORDER"})

ALLOWED_SCOPES = frozenset(
    {
        "advice",
        "research",
        "observation",
        "advice_research_observation",
    }
)


def capability_allowed(name: str) -> bool:
    return str(name or "").strip().lower() not in FORBIDDEN_CAPABILITIES


def scope_allowed(scope: str | None) -> bool:
    return str(scope or "advice_research_observation").strip() in ALLOWED_SCOPES


def strip_orders(advice: dict[str, Any] | None) -> dict[str, Any]:
    """Drop anything that could be read as an order. Keep the interpretation."""
    out = dict(advice or {})
    action = str(out.get("action") or "").strip().upper()
    if action in ORDER_ACTIONS:
        out["action"] = None
        out["stripped_order"] = True
        out["stripped_action"] = action
    for key in ("order", "orders", "quantity", "broker", "side", "limit_price"):
        if key in out and out[key] not in (None, "", [], {}):
            out[key] = None
            out["stripped_order"] = True
    out["never_orders"] = True
    out["advice_only"] = True
    return out
