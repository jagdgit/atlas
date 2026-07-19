"""PolicyService — the ``policy`` capability (Phase C · §C.5, CC8).

Governs durable operator rules (prefer/avoid/trust/distrust) that *influence* how Atlas retrieves
knowledge and phrases advice. Every mutation is journaled (before/after) so it is explainable (P9) and
reversible. The service also derives a bounded, signed **influence** list consumed by the retrieval
re-ranker and advice surfaces — **influence, not arbitration** (CC8): a rule nudges scoring, it never
hides a hit or decides an action.
"""

from __future__ import annotations

import logging
import re
from typing import Any

# Max additive re-rank delta a single rule contributes at strength=1.0. Larger than the experience
# soft-bias (0.005) because a policy is an explicit operator directive, yet still small enough that it
# nudges ranking rather than overriding relevance (influence, not arbitration).
POLICY_INFLUENCE_MAX = 0.02

# prefer/trust push up; avoid/distrust push down. Never a hard filter.
_SIGN = {"prefer": 1.0, "trust": 1.0, "avoid": -1.0, "distrust": -1.0}

_WORD_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)


def _tokenize(text: str) -> list[str]:
    return _WORD_RE.findall((text or "").lower())


class PolicyService:
    name = "policy"
    VERSION = "1.0.0"

    def __init__(
        self,
        repo: Any,
        *,
        influence_max: float = POLICY_INFLUENCE_MAX,
        logger: logging.Logger | None = None,
    ) -> None:
        self._repo = repo
        self._influence_max = influence_max
        self._logger = logger or logging.getLogger("atlas.policy")

    # --- mutations (all journaled) --------------------------------------
    def create_rule(
        self,
        subject: str,
        rule: str,
        *,
        scope: str = "global",
        strength: float = 1.0,
        enabled: bool = True,
        provenance: dict[str, Any] | None = None,
        created_by: str | None = None,
    ) -> dict[str, Any]:
        """Create (or upsert) a rule and journal it. Returns the stored rule."""
        existing = self._repo.get_by_natural(scope, subject, rule)
        row = self._repo.create(
            scope, subject, rule, strength=strength, enabled=enabled,
            provenance=provenance, created_by=created_by,
        )
        self._repo.record_event(
            row["id"], "updated" if existing else "created",
            before=existing, after=row, actor=created_by,
        )
        return row

    def update_rule(
        self, rule_id: str, *, actor: str | None = None, **fields: Any
    ) -> dict[str, Any]:
        before = self._require(rule_id)
        after = self._repo.update(rule_id, **fields)
        self._repo.record_event(rule_id, "updated", before=before, after=after, actor=actor)
        return after

    def set_enabled(
        self, rule_id: str, enabled: bool, *, actor: str | None = None
    ) -> dict[str, Any]:
        before = self._require(rule_id)
        after = self._repo.set_enabled(rule_id, enabled)
        self._repo.record_event(
            rule_id, "enabled" if enabled else "disabled",
            before=before, after=after, actor=actor,
        )
        return after

    def delete_rule(self, rule_id: str, *, actor: str | None = None) -> dict[str, Any]:
        before = self._require(rule_id)
        self._repo.delete(rule_id)
        self._repo.record_event(rule_id, "deleted", before=before, after=None, actor=actor)
        return before

    def revert(self, event_id: str, *, actor: str | None = None) -> dict[str, Any] | None:
        """Undo the change recorded by ``event_id``, restoring the rule's prior state (P9)."""
        ev = self._repo.get_event(event_id)
        if ev is None:
            raise KeyError(f"no policy event {event_id}")
        action = ev["action"]
        before, after, rule_id = ev["before"], ev["after"], ev["rule_id"]
        if action == "reverted":
            raise ValueError("cannot revert a revert event")

        if action == "created":
            # Undo a creation → remove the rule.
            if rule_id and self._repo.get(rule_id):
                self._repo.delete(rule_id)
            restored = None
        elif action == "deleted":
            # Undo a deletion → re-insert the snapshot (same id).
            restored = self._repo.restore(before)
        else:  # updated | enabled | disabled → restore the before snapshot
            if before is None:
                raise ValueError("event has no before-state to revert to")
            if rule_id and self._repo.get(rule_id):
                restored = self._repo.update(
                    rule_id,
                    subject=before.get("subject"),
                    strength=before.get("strength"),
                    enabled=before.get("enabled"),
                    provenance=before.get("provenance"),
                )
            else:
                restored = self._repo.restore(before)
        self._repo.record_event(rule_id, "reverted", before=after, after=restored, actor=actor)
        return restored

    # --- reads ----------------------------------------------------------
    def get_rule(self, rule_id: str) -> dict[str, Any] | None:
        return self._repo.get(rule_id)

    def list_rules(
        self, *, scope: str | None = None, rule: str | None = None,
        enabled: bool | None = None, limit: int = 200,
    ) -> list[dict[str, Any]]:
        return self._repo.list(scope=scope, rule=rule, enabled=enabled, limit=limit)

    def list_events(
        self, *, rule_id: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        return self._repo.list_events(rule_id=rule_id, limit=limit)

    # --- influence (consumed by retrieval + advice) ---------------------
    def retrieval_influence(self, *, scope: str | None = None) -> list[dict[str, Any]]:
        """Signed, bounded influence for enabled rules — the re-ranker/advice input.

        Each entry: ``{id, rule, subject, scope, terms, weight}`` where ``weight`` is
        ``sign(rule) * strength * influence_max`` (positive boosts, negative deprioritizes). Rules
        scoped ``global`` always apply; a caller ``scope`` additionally admits rules with that exact
        scope. When no ``scope`` is requested, only ``global`` rules apply (mission/domain-scoped
        rules never leak into unrelated retrieval).
        """
        allowed = {"global"} if scope is None else {"global", scope}
        out: list[dict[str, Any]] = []
        for r in self._repo.list(enabled=True, limit=500):
            if r["scope"] not in allowed:
                continue
            sign = _SIGN.get(r["rule"], 0.0)
            weight = sign * float(r["strength"]) * self._influence_max
            terms = _tokenize(r["subject"])
            if not terms or weight == 0.0:
                continue
            out.append({
                "id": str(r["id"]),
                "rule": r["rule"],
                "subject": r["subject"],
                "scope": r["scope"],
                "terms": terms,
                "weight": weight,
            })
        return out

    # advice surfaces use the same signed influence.
    advice_influence = retrieval_influence

    # --- internals ------------------------------------------------------
    def _require(self, rule_id: str) -> dict[str, Any]:
        row = self._repo.get(rule_id)
        if row is None:
            raise KeyError(f"no policy rule {rule_id}")
        return row
