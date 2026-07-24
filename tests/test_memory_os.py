"""Memory OS hierarchy (MEM.1)."""

from __future__ import annotations

from atlas.memory import (
    LAYER_LONG_TERM,
    LAYER_SESSION,
    LAYER_WORKING,
    MemoryOS,
)
from atlas.missions.context import MissionContextService


class _Mem:
    def __init__(self) -> None:
        self.items: dict[str, object] = {}
        self._n = 0

    def remember(
        self,
        content,
        *,
        kind="semantic",
        scope="global",
        importance=0.0,
        metadata=None,
        ttl_seconds=None,
        **_,
    ):
        self._n += 1
        mid = f"m{self._n}"

        class _Item:
            pass

        it = _Item()
        it.id = mid
        it.kind = kind
        it.content = content
        it.scope = scope
        it.importance = importance
        it.metadata = dict(metadata or {})
        it.similarity = None
        it.as_dict = lambda: {
            "id": mid,
            "kind": kind,
            "content": content,
            "scope": scope,
            "importance": importance,
            "metadata": it.metadata,
        }
        self.items[mid] = it
        return it

    def recent(self, *, kind=None, scope=None, limit=20):
        out = []
        for it in self.items.values():
            if kind and it.kind != kind:
                continue
            if scope and it.scope != scope:
                continue
            out.append(it)
        return out[:limit]

    def recall(self, query, *, limit=5, kind=None, scope=None):
        return self.recent(kind=kind, scope=scope, limit=limit)

    def forget(self, memory_id):
        return self.items.pop(str(memory_id), None) is not None


def test_hierarchy_shape():
    mos = MemoryOS(_Mem())
    h = mos.hierarchy()
    layers = [x["layer"] for x in h["layers"]]
    assert layers == ["working", "session", "long_term", "knowledge", "experience"]
    assert h["version"] == "mem.1"


def test_remember_and_promote():
    mem = _Mem()
    mos = MemoryOS(mem)
    r = mos.remember("scratch note about NSE", layer=LAYER_WORKING)
    assert r["ok"]
    mid = r["item"]["id"]
    p = mos.promote(mid, to_layer=LAYER_SESSION)
    assert p["ok"]
    assert p["layer"] == LAYER_SESSION
    p2 = mos.promote(p["item"]["id"], to_layer=LAYER_LONG_TERM)
    assert p2["ok"]
    assert p2["layer"] == LAYER_LONG_TERM


def test_cannot_promote_to_knowledge():
    mem = _Mem()
    mos = MemoryOS(mem)
    r = mos.remember("x", layer=LAYER_WORKING)
    out = mos.promote(r["item"]["id"], to_layer="knowledge")
    assert out["ok"] is False


def test_mission_context_includes_memory():
    mem = _Mem()
    mos = MemoryOS(mem)
    mos.remember("cash flow lesson", layer=LAYER_LONG_TERM)
    ctx = MissionContextService(memory_os=mos)
    out = ctx.gather("cash flow", limit=8)
    assert "memory" in out["sources"] or any(
        i.get("item_kind") == "memory" for i in out["items"]
    )
