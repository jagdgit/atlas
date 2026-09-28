"""NOW #7 — attach news / policy / historical evidence into scientist packets.

Reads durable stores only. Empty → explicit unknowns. Never invents headlines,
policy titles, PE/FCF, or bar returns.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

VERSION = "now.world_evidence.v1"
_log = logging.getLogger("atlas.investment.world_evidence")


def attach_world_evidence(
    data_dir: str | Path | None,
    symbol: str | None,
    *,
    laboratory_id: str | None = None,
    sector: str | None = None,
    limit_news: int = 3,
    limit_policy: int = 2,
    bar_lookback: int = 30,
) -> dict[str, Any]:
    """Pull citeable news + policy + history lines for one symbol.

    Honesty: missing lanes become unknowns_* — never fabricated text.
    """
    sym = str(symbol or "").strip().upper()
    out: dict[str, Any] = {
        "version": VERSION,
        "kind": "WORLD_EVIDENCE",
        "symbol": sym or None,
        "laboratory_id": laboratory_id,
        "evidence_lines": [],
        "evidence_ids": [],
        "unknowns": [],
        "news": [],
        "policy": [],
        "history": None,
        "honesty": (
            "World evidence — cite only stored news/policy/bars. "
            "Empty lane → unknown_explicit. Never invent PE/FCF/headlines."
        ),
    }
    if not data_dir or not sym:
        out["unknowns"] = ["news", "policy", "history", "no_symbol_or_data_dir"]
        return out

    lines: list[str] = []
    ids: list[str] = []
    unknowns: list[str] = []

    # --- news ---
    news_items: list[dict[str, Any]] = []
    try:
        from atlas.investment.observations import DecisionObservationStore
        from atlas.investment.open_book_packs import _news_block_from_observations
        from atlas.investment.symbol_aliases import news_is_evidence

        store = DecisionObservationStore(data_dir=str(data_dir))
        rows = store.list_news_for_symbol(symbol=sym, limit=max(12, limit_news * 4), since_hours=168.0)
        block = _news_block_from_observations(rows)
        for bucket in ("company", "sector", "gov", "macro"):
            for item in block.get(bucket) or []:
                if not isinstance(item, dict):
                    continue
                title = str(item.get("title") or "").strip()
                if not title:
                    continue
                oid = str(item.get("id") or "")
                news_items.append(
                    {
                        "id": oid or None,
                        "lane": bucket,
                        "title": title[:160],
                        "published_at": item.get("published_at"),
                    }
                )
                line = f"news:{bucket}:{title[:140]}"
                lines.append(line)
                if oid:
                    ids.append(oid)
                if len(news_items) >= max(1, int(limit_news)):
                    break
            if len(news_items) >= max(1, int(limit_news)):
                break
        # OI-WEB-EVID0 — DuckDuckGo candidates are tier-3 discovery (not auto-evidence);
        # still attach explicitly so scientist can evaluate (never invent).
        if len(news_items) < max(1, int(limit_news)):
            for r in rows:
                if not isinstance(r, dict):
                    continue
                pl = r.get("payload") if isinstance(r.get("payload"), dict) else {}
                src = str(r.get("source") or pl.get("source") or "")
                if src != "duckduckgo_search" and pl.get("evidence_class") != "evidence_candidate":
                    continue
                title = str(
                    pl.get("title") or pl.get("text") or r.get("summary") or ""
                ).strip()
                if not title:
                    continue
                oid = str(r.get("id") or "")
                news_items.append(
                    {
                        "id": oid or None,
                        "lane": "web_search",
                        "title": title[:160],
                        "url": pl.get("link"),
                        "published_at": pl.get("published_at") or r.get("created_at"),
                        "honesty": "search_snippet_candidate",
                    }
                )
                lines.append(f"news:web_search:{title[:140]}")
                if oid:
                    ids.append(oid)
                if len(news_items) >= max(1, int(limit_news)):
                    break
        # Prefer evidence-grade only; if all seed, stay empty
        if not news_items and rows:
            evid_n = sum(1 for r in rows if isinstance(r, dict) and news_is_evidence(r))
            if evid_n == 0:
                unknowns.append("news_evidence_grade")
        if not news_items:
            unknowns.append("news")
        for u in block.get("unknowns") or []:
            # keep pack-style unknowns only when that lane empty for this symbol slice
            pass
    except Exception:  # noqa: BLE001
        _log.debug("world_evidence news read failed", exc_info=True)
        unknowns.append("news")

    out["news"] = news_items[: max(1, int(limit_news))]

    # --- policy ---
    policy_items: list[dict[str, Any]] = []
    try:
        from atlas.investment.government_policy import load_snapshot

        snap = load_snapshot(data_dir)
        sector_key = (sector or "").strip().lower()
        items = list(snap.get("items") or [])
        scored: list[tuple[float, dict[str, Any]]] = []
        for it in items:
            if not isinstance(it, dict):
                continue
            secs = [str(s).lower() for s in (it.get("sectors") or []) if s]
            score = 0.0
            if sector_key and any(sector_key in s or s in sector_key for s in secs):
                score += 2.0
            # Pharma/chemicals soft match for CIPLA-like names without sector arg
            if not sector_key and any(
                k in " ".join(secs)
                for k in ("pharma", "health", "chemical", "auto", "bank", "it ")
            ):
                score += 0.5
            score += abs(float(it.get("delta") or 0.0))
            scored.append((score, it))
        scored.sort(key=lambda x: -x[0])
        for _, it in scored[: max(1, int(limit_policy))]:
            title = str(it.get("title") or "").strip()
            if not title:
                continue
            pid = str(it.get("id") or "")
            delta = it.get("delta")
            policy_items.append(
                {
                    "id": pid or None,
                    "title": title[:160],
                    "delta": delta,
                    "sectors": list(it.get("sectors") or [])[:6],
                }
            )
            lines.append(
                f"policy:{title[:120]}"
                + (f":delta={float(delta):+.2f}" if delta is not None else "")
            )
            if pid:
                ids.append(f"policy:{pid}")
        if not policy_items:
            unknowns.append("policy")
    except Exception:  # noqa: BLE001
        _log.debug("world_evidence policy read failed", exc_info=True)
        unknowns.append("policy")

    out["policy"] = policy_items[: max(1, int(limit_policy))]

    # --- history (bars) ---
    history: dict[str, Any] | None = None
    try:
        from atlas.investment.bar_store import load_bars
        from atlas.investment.open_book_packs import (
            last_bar_return_pct,
            regime_tags_from_bars,
        )

        bars = load_bars(data_dir, sym, limit=max(5, int(bar_lookback)))
        if bars:
            last = bars[-1] if isinstance(bars[-1], dict) else {}
            ret1 = last_bar_return_pct(bars)
            ret5 = None
            if len(bars) >= 6:
                try:
                    c0 = float(bars[-6].get("close") or bars[-6].get("Close") or 0)
                    c1 = float(last.get("close") or last.get("Close") or 0)
                    if c0 > 0 and c1 > 0:
                        ret5 = round((c1 / c0 - 1.0) * 100.0, 3)
                except (TypeError, ValueError):
                    ret5 = None
            tags = regime_tags_from_bars(bars)[:6]
            history = {
                "bar_count": len(bars),
                "last_date": last.get("date") or last.get("Date"),
                "last_close": last.get("close") or last.get("Close"),
                "ret_1d_pct": ret1,
                "ret_5d_pct": ret5,
                "regime_tags": tags,
            }
            lines.append(
                f"history:bars={len(bars)}"
                f":last={history.get('last_date')}"
                f":close={history.get('last_close')}"
                + (f":ret1d={ret1:+.3f}%" if ret1 is not None else ":ret1d=unknown")
                + (f":ret5d={ret5:+.3f}%" if ret5 is not None else "")
                + (f":regime={','.join(tags)}" if tags else "")
            )
            ids.append(f"bars:{sym}:{history.get('last_date') or 'n'}")
        else:
            unknowns.append("history")
    except Exception:  # noqa: BLE001
        _log.debug("world_evidence history read failed", exc_info=True)
        unknowns.append("history")

    out["history"] = history
    # de-dupe preserve order
    seen: set[str] = set()
    uniq_lines: list[str] = []
    for ln in lines:
        if ln in seen:
            continue
        seen.add(ln)
        uniq_lines.append(ln[:220])
    out["evidence_lines"] = uniq_lines[:16]
    out["evidence_ids"] = list(dict.fromkeys(ids))[:24]
    out["unknowns"] = list(dict.fromkeys(unknowns))[:12]
    return out


def apply_world_to_scientist_packet(
    packet: dict[str, Any] | None,
    world: dict[str, Any] | None,
) -> dict[str, Any]:
    """Fold world evidence into Stage-3 scientist packet (advice-only context)."""
    pkt = dict(packet) if isinstance(packet, dict) else {}
    world = world if isinstance(world, dict) else {}
    evid = [str(x) for x in (pkt.get("evidence_ids") or []) if x]
    for x in world.get("evidence_ids") or []:
        if x and str(x) not in evid:
            evid.append(str(x))
    unk = [str(x) for x in (pkt.get("unknowns") or []) if x]
    for x in world.get("unknowns") or []:
        tag = f"world_{x}" if not str(x).startswith("world_") else str(x)
        if tag not in unk and str(x) not in unk:
            unk.append(str(x) if str(x).startswith("world_") else f"world_{x}")
    pkt["evidence_ids"] = evid[:40]
    pkt["unknowns"] = unk[:20]
    pkt["world_evidence"] = {
        "version": world.get("version") or VERSION,
        "evidence_lines": list(world.get("evidence_lines") or [])[:16],
        "news_n": len(world.get("news") or []),
        "policy_n": len(world.get("policy") or []),
        "history": world.get("history"),
        "unknowns": list(world.get("unknowns") or [])[:12],
    }
    return pkt


def apply_world_to_evidence_packet(
    packet: dict[str, Any] | None,
    world: dict[str, Any] | None,
) -> dict[str, Any]:
    """Fold world evidence into Cognitive Core evidence packet."""
    pkt = dict(packet) if isinstance(packet, dict) else {}
    world = world if isinstance(world, dict) else {}
    evid = [str(x) for x in (pkt.get("evidence") or []) if x]
    for ln in world.get("evidence_lines") or []:
        if ln and str(ln) not in evid:
            evid.append(str(ln)[:220])
    unk = [str(x) for x in (pkt.get("unknowns") or []) if x]
    for x in world.get("unknowns") or []:
        tag = str(x)
        if tag not in unk:
            unk.append(tag)
    known = [str(x) for x in (pkt.get("known") or []) if x]
    hist = world.get("history") if isinstance(world.get("history"), dict) else None
    if hist and hist.get("last_close") is not None:
        known.append(
            f"last_close={hist.get('last_close')}@{hist.get('last_date')}"
        )
    pkt["evidence"] = evid[:40]
    pkt["unknowns"] = unk[:20]
    pkt["known"] = known[:20]
    pkt["world_evidence"] = {
        "version": world.get("version") or VERSION,
        "news_n": len(world.get("news") or []),
        "policy_n": len(world.get("policy") or []),
        "history": hist,
        "unknowns": list(world.get("unknowns") or [])[:12],
    }
    return pkt
