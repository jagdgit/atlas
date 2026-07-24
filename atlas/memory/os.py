"""Memory OS — explicit hierarchy over ``memory.items`` (OI-PA-MEM / MEM.1).

Maps platform layers to durable kinds without inventing a second store:

```
working   → kind=working   (TTL scratch / active tick)
session   → kind=episodic  (metadata.layer=session; recent decisions / job workspace)
long_term → kind=semantic  (durable recall)
knowledge → Knowledge OS   (not memory.items — consolidator findings)
experience→ Experience OS  (not memory.items — lessons)
```

Promotion moves content up the ladder; Knowledge/Experience writes stay on those
OS services (honest boundaries).
"""

from __future__ import annotations

import logging
from typing import Any

# Platform layer → memory.items kind (+ metadata markers)
LAYER_WORKING = "working"
LAYER_SESSION = "session"
LAYER_LONG_TERM = "long_term"
LAYER_KNOWLEDGE = "knowledge"
LAYER_EXPERIENCE = "experience"

_LAYER_TO_KIND = {
    LAYER_WORKING: "working",
    LAYER_SESSION: "episodic",
    LAYER_LONG_TERM: "semantic",
}

_KIND_TO_LAYER = {
    "working": LAYER_WORKING,
    "episodic": LAYER_SESSION,
    "semantic": LAYER_LONG_TERM,
}

HIERARCHY = [
    {
        "layer": LAYER_WORKING,
        "kind": "working",
        "role": "Today's research scratch / active tick context",
        "ttl": True,
        "store": "memory.items",
    },
    {
        "layer": LAYER_SESSION,
        "kind": "episodic",
        "role": "Recent decisions & job workspace",
        "ttl": False,
        "store": "memory.items",
        "metadata": {"layer": "session"},
    },
    {
        "layer": LAYER_LONG_TERM,
        "kind": "semantic",
        "role": "Durable recall (existing MemoryService)",
        "ttl": False,
        "store": "memory.items",
    },
    {
        "layer": LAYER_KNOWLEDGE,
        "kind": None,
        "role": "Consolidated findings (Knowledge OS) — not memory.items",
        "ttl": False,
        "store": "knowledge",
    },
    {
        "layer": LAYER_EXPERIENCE,
        "kind": None,
        "role": "Lessons from outcomes (Experience OS) — not memory.items",
        "ttl": False,
        "store": "experience",
    },
]


class MemoryOS:
    """Hierarchy façade over :class:`~atlas.services.memory_service.MemoryService`."""

    name = "memory_os"
    VERSION = "mem.1"

    def __init__(
        self,
        memory: Any,
        *,
        learning: Any | None = None,
        knowledge: Any | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._memory = memory
        self._learning = learning
        self._knowledge = knowledge
        self._logger = logger or logging.getLogger("atlas.memory.os")

    def hierarchy(self) -> dict[str, Any]:
        return {
            "layers": list(HIERARCHY),
            "rule": (
                "scratch → working; important conclusion → Knowledge; "
                "repeated pattern → Experience; durable facts → long_term"
            ),
            "version": self.VERSION,
        }

    def remember(
        self,
        content: str,
        *,
        layer: str = LAYER_LONG_TERM,
        scope: str = "global",
        importance: float = 0.0,
        metadata: dict[str, Any] | None = None,
        session_id: str | None = None,
        ttl_seconds: int | None = None,
    ) -> dict[str, Any]:
        """Store content at a hierarchy layer (working / session / long_term)."""
        layer_l = (layer or LAYER_LONG_TERM).strip().lower()
        if layer_l in {LAYER_KNOWLEDGE, LAYER_EXPERIENCE}:
            return {
                "ok": False,
                "error": (
                    f"layer {layer_l!r} is not memory.items — use Knowledge OS / "
                    "Experience OS (remember_experience) instead"
                ),
                "layer": layer_l,
                "version": self.VERSION,
            }
        kind = _LAYER_TO_KIND.get(layer_l)
        if kind is None:
            raise ValueError(
                f"unknown memory layer: {layer!r} "
                f"(use working|session|long_term)"
            )
        meta = dict(metadata or {})
        meta["layer"] = layer_l
        if session_id:
            meta["session_id"] = str(session_id)
            if scope == "global":
                scope = f"session:{session_id}"
        item = self._memory.remember(
            content,
            kind=kind,
            scope=scope,
            importance=importance,
            metadata=meta,
            ttl_seconds=ttl_seconds,
        )
        return {
            "ok": True,
            "layer": layer_l,
            "item": _item_dict(item),
            "version": self.VERSION,
        }

    def promote(
        self,
        memory_id: str,
        *,
        to_layer: str,
        forget_source: bool = False,
        importance: float | None = None,
    ) -> dict[str, Any]:
        """Promote a memory item up the hierarchy (working→session→long_term)."""
        to_layer = (to_layer or "").strip().lower()
        if to_layer in {LAYER_KNOWLEDGE, LAYER_EXPERIENCE}:
            return {
                "ok": False,
                "error": (
                    f"Cannot promote into {to_layer} via Memory OS — write Knowledge "
                    "findings or Experience lessons on those services"
                ),
                "version": self.VERSION,
            }
        if to_layer not in _LAYER_TO_KIND:
            raise ValueError(f"unknown to_layer: {to_layer!r}")

        get = getattr(self._memory, "_repo", None)
        src = None
        if get is not None and hasattr(get, "get"):
            src = get.get(memory_id)
        if src is None:
            # Fall back: scan recent
            for kind in ("working", "episodic", "semantic"):
                for it in self._memory.recent(kind=kind, limit=50):
                    if str(getattr(it, "id", "")) == str(memory_id):
                        src = it
                        break
                if src is not None:
                    break
        if src is None:
            return {"ok": False, "error": f"memory not found: {memory_id}", "version": self.VERSION}

        from_layer = _KIND_TO_LAYER.get(str(getattr(src, "kind", "")), "unknown")
        order = [LAYER_WORKING, LAYER_SESSION, LAYER_LONG_TERM]
        if from_layer in order and to_layer in order:
            if order.index(to_layer) < order.index(from_layer):
                return {
                    "ok": False,
                    "error": f"cannot demote {from_layer} → {to_layer}",
                    "version": self.VERSION,
                }

        meta = dict(getattr(src, "metadata", None) or {})
        meta["layer"] = to_layer
        meta["promoted_from"] = str(memory_id)
        meta["promoted_from_layer"] = from_layer
        imp = float(importance) if importance is not None else float(
            getattr(src, "importance", 0.0) or 0.0
        )
        out = self.remember(
            str(getattr(src, "content", "")),
            layer=to_layer,
            scope=str(getattr(src, "scope", "global") or "global"),
            importance=imp,
            metadata=meta,
        )
        if forget_source and out.get("ok"):
            try:
                self._memory.forget(str(memory_id))
            except Exception as exc:  # noqa: BLE001
                self._logger.warning("forget source after promote failed: %s", exc)
        out["from_layer"] = from_layer
        out["from_id"] = str(memory_id)
        return out

    def context_for(
        self,
        topic: str,
        *,
        limit: int = 6,
        session_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Compact memory rows for Mission Context (working + session + long_term)."""
        topic = (topic or "").strip()
        rows: list[dict[str, Any]] = []
        # Prefer semantic recall when query present; always mix recent working.
        if topic:
            try:
                hits = self._memory.recall(topic, limit=max(1, limit // 2)) or []
                for it in hits:
                    rows.append(_as_context_item(it))
            except Exception as exc:  # noqa: BLE001 — embeddings may be offline
                self._logger.debug("memory recall skipped: %s", exc)
        for kind, layer in (
            ("working", LAYER_WORKING),
            ("episodic", LAYER_SESSION),
        ):
            try:
                scope = f"session:{session_id}" if session_id and kind == "episodic" else None
                for it in self._memory.recent(kind=kind, scope=scope, limit=3) or []:
                    row = _as_context_item(it)
                    if row["id"] in {r["id"] for r in rows}:
                        continue
                    rows.append(row)
                    if len(rows) >= limit:
                        return rows
            except Exception as exc:  # noqa: BLE001
                self._logger.debug("memory recent(%s) skipped: %s", kind, exc)
        return rows[:limit]


def _item_dict(item: Any) -> dict[str, Any]:
    if hasattr(item, "as_dict"):
        return item.as_dict()
    return {
        "id": str(getattr(item, "id", "")),
        "kind": getattr(item, "kind", None),
        "content": getattr(item, "content", None),
        "scope": getattr(item, "scope", None),
        "importance": getattr(item, "importance", None),
        "metadata": getattr(item, "metadata", None) or {},
    }


def _as_context_item(item: Any) -> dict[str, Any]:
    kind = str(getattr(item, "kind", "") or "")
    layer = _KIND_TO_LAYER.get(kind, kind)
    meta = getattr(item, "metadata", None) or {}
    if isinstance(meta, dict) and meta.get("layer"):
        layer = str(meta["layer"])
    return {
        "item_kind": "memory",
        "kind": kind,
        "layer": layer,
        "id": str(getattr(item, "id", "")),
        "content": str(getattr(item, "content", "") or "")[:400],
        "scope": getattr(item, "scope", None),
        "similarity": getattr(item, "similarity", None),
    }
