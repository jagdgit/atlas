"""Policy Engine — hard/soft constraint evaluation (OI-PA-POLICY / PA.2).

Builds on the Phase-C Policy store (prefer/avoid/trust/distrust = soft influence).
Adds reusable hard constraints:

- ``forbid`` — block matching actions (e.g. forbid subject=TSLA on buys)
- ``limit`` — numeric caps via provenance ``max_position_pct`` / ``max_exposure_pct`` /
  ``max_drawdown_pct`` (refuse when context breaches)

Soft rules still only nudge scores; hard rules never invent trades — they only
block or allow. Simulation remains free of broker side effects (P10).
"""

from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass, field
from typing import Any

_WORD = re.compile(r"[a-z0-9.+-]+", re.I)

SOFT_RULES = frozenset({"prefer", "avoid", "trust", "distrust"})
HARD_RULES = frozenset({"forbid", "limit"})


@dataclass
class PolicyVerdict:
    allowed: bool
    soft_delta: float = 0.0
    hard_violations: list[dict[str, Any]] = field(default_factory=list)
    soft_notes: list[dict[str, Any]] = field(default_factory=list)
    matched_rules: list[str] = field(default_factory=list)
    version: str = "pa.2"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class PolicyEngine:
    """Evaluate an intended action against Policy rules (hard + soft)."""

    name = "policy_engine"
    VERSION = "pa.2"

    def __init__(
        self,
        policy: Any,
        *,
        soft_weight: float = 0.15,
        logger: logging.Logger | None = None,
    ) -> None:
        self._policy = policy
        self._soft_weight = soft_weight
        self._logger = logger or logging.getLogger("atlas.policy.engine")

    def evaluate(
        self,
        *,
        action: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
        scope: str | None = None,
        scopes: list[str] | None = None,
    ) -> dict[str, Any]:
        """Return a :class:`PolicyVerdict` as a dict.

        ``action`` examples: ``{kind: buy, symbol: RELIANCE.NS, quantity: 10}``.
        ``context`` may include ``equity``, ``position_qty``, ``exposure_pct``,
        ``drawdown_pct``, ``text`` (free-form goal string), ``domain`` / ``domains``
        (OI-C9 — admit matching scoped rules alongside ``global``).
        """
        action = action or {}
        context = context or {}
        kind = str(action.get("kind") or action.get("side") or "").strip().lower()
        symbol = str(action.get("symbol") or "").strip()
        text = " ".join(
            [
                symbol,
                kind,
                str(action.get("text") or ""),
                str(context.get("text") or ""),
                str(context.get("goal") or ""),
            ]
        ).lower()

        extra_scopes = list(scopes or [])
        domain = context.get("domain") or context.get("knowledge_domain")
        if domain:
            extra_scopes.append(f"domain:{domain}")
        for d in context.get("domains") or []:
            raw = str(d or "").strip()
            if raw:
                extra_scopes.append(raw if raw.startswith("domain:") else f"domain:{raw}")
        mission_id = context.get("mission_id")
        if mission_id:
            extra_scopes.append(f"mission:{mission_id}")
        mission_type = context.get("mission_type")
        if mission_type:
            extra_scopes.append(f"mission_type:{mission_type}")

        rules = self._load_rules(scope=scope, scopes=extra_scopes)
        hard_violations: list[dict[str, Any]] = []
        soft_notes: list[dict[str, Any]] = []
        matched: list[str] = []
        soft_delta = 0.0

        for r in rules:
            rule = str(r.get("rule") or "").strip().lower()
            subject = str(r.get("subject") or "").strip()
            if not subject:
                continue
            if not _subject_matches(subject, text=text, symbol=symbol):
                continue
            rid = str(r.get("id") or "")
            matched.append(rid or f"{rule}:{subject}")

            if rule == "forbid":
                hard_violations.append(
                    {
                        "rule_id": rid,
                        "rule": rule,
                        "subject": subject,
                        "detail": f"forbid matched {subject!r} for action {kind or 'any'}",
                    }
                )
            elif rule == "limit":
                viol = _check_limit(r, action=action, context=context)
                if viol:
                    hard_violations.append(viol)
            elif rule in SOFT_RULES:
                strength = float(r.get("strength") or 1.0)
                sign = 1.0 if rule in {"prefer", "trust"} else -1.0
                # Prefer/trust on buy of subject → +; avoid on buy → -
                if kind in {"buy", "sell", ""}:
                    delta = sign * strength * self._soft_weight
                    soft_delta += delta
                    soft_notes.append(
                        {
                            "rule_id": rid,
                            "rule": rule,
                            "subject": subject,
                            "delta": round(delta, 4),
                            "detail": "soft influence only",
                        }
                    )

        allowed = len(hard_violations) == 0
        return PolicyVerdict(
            allowed=allowed,
            soft_delta=round(soft_delta, 4),
            hard_violations=hard_violations,
            soft_notes=soft_notes,
            matched_rules=matched[:20],
        ).as_dict()

    def _load_rules(
        self, *, scope: str | None = None, scopes: list[str] | None = None
    ) -> list[dict[str, Any]]:
        try:
            rows = self._policy.list_rules(enabled=True, limit=500) or []
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("list_rules failed: %s", exc)
            return []
        allowed_scopes: set[str] = {"global"}
        if scope:
            allowed_scopes.add(str(scope))
        for s in scopes or []:
            raw = str(s or "").strip()
            if raw:
                allowed_scopes.add(raw)
        return [r for r in rows if str(r.get("scope") or "global") in allowed_scopes]


def _subject_matches(subject: str, *, text: str, symbol: str) -> bool:
    subj = subject.lower().strip()
    if not subj:
        return False
    if symbol and subj == symbol.lower():
        return True
    if subj in text:
        return True
    tokens = _WORD.findall(subj)
    if len(tokens) == 1 and tokens[0] in text.split():
        return True
    return False


def _check_limit(
    rule: dict[str, Any],
    *,
    action: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any] | None:
    prov = rule.get("provenance") if isinstance(rule.get("provenance"), dict) else {}
    rid = str(rule.get("id") or "")
    subject = str(rule.get("subject") or "")

    max_pos = _as_float(prov.get("max_position_pct") or prov.get("max_position_qty"))
    max_exp = _as_float(prov.get("max_exposure_pct"))
    max_dd = _as_float(prov.get("max_drawdown_pct"))

    exposure = _as_float(context.get("exposure_pct"))
    drawdown = _as_float(context.get("drawdown_pct"))
    pos_qty = _as_float(context.get("position_qty")) or 0.0
    qty = _as_float(action.get("quantity")) or 0.0
    equity = _as_float(context.get("equity")) or 0.0
    price = _as_float(action.get("price") or context.get("price")) or 0.0

    if max_exp is not None and exposure is not None and exposure > max_exp:
        return {
            "rule_id": rid,
            "rule": "limit",
            "subject": subject,
            "detail": f"exposure {exposure:g}% exceeds max_exposure_pct {max_exp:g}",
        }
    if max_dd is not None and drawdown is not None and drawdown > max_dd:
        return {
            "rule_id": rid,
            "rule": "limit",
            "subject": subject,
            "detail": f"drawdown {drawdown:g}% exceeds max_drawdown_pct {max_dd:g}",
        }
    if max_pos is not None:
        # Treat as qty cap when value >= 1 and no % key; else percent of equity notional.
        if prov.get("max_position_pct") is not None and equity > 0 and price > 0:
            notional = (pos_qty + qty) * price
            pct = 100.0 * notional / equity
            if pct > max_pos:
                return {
                    "rule_id": rid,
                    "rule": "limit",
                    "subject": subject,
                    "detail": (
                        f"position {pct:.1f}% of equity exceeds max_position_pct {max_pos:g}"
                    ),
                }
        elif pos_qty + qty > max_pos:
            return {
                "rule_id": rid,
                "rule": "limit",
                "subject": subject,
                "detail": f"quantity {pos_qty + qty:g} exceeds max_position {max_pos:g}",
            }
    return None


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
