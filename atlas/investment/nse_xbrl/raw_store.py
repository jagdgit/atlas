"""Keep original XBRL bytes. Hash + path. Append-only."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STORE_REL = Path("investment") / "fundamentals" / "raw" / "nse_xbrl"


def _safe(s: str) -> str:
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in (s or ""))[:80]


def store_raw(
    data_dir: str | Path | None,
    *,
    symbol: str,
    xml_text: str | bytes,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not data_dir:
        return {"ok": False, "reason": "no_data_dir"}
    raw = xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text
    digest = hashlib.sha256(raw).hexdigest()
    sym = _safe(str(symbol or "SYM").upper())
    root = Path(data_dir) / STORE_REL / sym
    root.mkdir(parents=True, exist_ok=True)
    xml_path = root / f"{digest[:16]}.xml"
    meta_path = root / f"{digest[:16]}.json"
    if not xml_path.exists():
        xml_path.write_bytes(raw)
    doc = {
        "symbol": str(symbol or "").upper(),
        "sha256": digest,
        "path": str(xml_path.relative_to(Path(data_dir))),
        "stored_at": datetime.now(timezone.utc).isoformat(),
        "bytes": len(raw),
        "meta": meta if isinstance(meta, dict) else {},
        "canonical": bool((meta or {}).get("canonical")),
    }
    meta_path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return {"ok": True, "raw_evidence_id": digest, "path": str(xml_path), "meta": doc}


def list_raw(data_dir: str | Path | None, symbol: str) -> list[dict[str, Any]]:
    if not data_dir:
        return []
    root = Path(data_dir) / STORE_REL / _safe(str(symbol or "").upper())
    if not root.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for p in sorted(root.glob("*.json")):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return out


def load_stored_xml(
    data_dir: str | Path | None, symbol: str
) -> list[dict[str, Any]]:
    """Return stored XBRL documents for replay. Canonical last. Never fetches NSE."""
    if not data_dir:
        return []
    from atlas.investment.fundamentals import normalize_symbol

    raw_sym = str(symbol or "").strip()
    names = []
    for cand in (raw_sym, normalize_symbol(raw_sym), raw_sym.replace(".NS", "").replace(".BO", "")):
        if cand and cand not in names:
            names.append(cand)
            ns = cand if cand.endswith(".NS") else f"{cand}.NS"
            if ns not in names:
                names.append(ns)
    seen: set[str] = set()
    docs: list[dict[str, Any]] = []
    root = Path(data_dir)
    for name in names:
        for item in list_raw(data_dir, name):
            digest = str(item.get("sha256") or "")
            if digest in seen:
                continue
            rel = str(item.get("path") or "")
            path = (root / rel) if rel and not Path(rel).is_absolute() else Path(rel)
            if not path.is_file():
                continue
            try:
                xml = path.read_text(encoding="utf-8")
            except OSError:
                continue
            if not xml.strip():
                continue
            seen.add(digest)
            meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
            docs.append(
                {
                    "xml": xml,
                    "sha256": digest,
                    "path": str(path),
                    "canonical": bool(item.get("canonical") or meta.get("canonical")),
                    "role": meta.get("role"),
                    "available_at": meta.get("available_at"),
                    "bytes": item.get("bytes"),
                }
            )
    docs.sort(key=lambda d: (1 if d.get("canonical") else 0, str(d.get("sha256") or "")))
    return docs
