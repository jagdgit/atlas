"""IIP.4 — Company document import (AR / quarterly / deck / transcript).

Operator drop or API → text extract (PDF text layer + optional OCR) →
guidance / risks / KPI claims → durable manifest → IRA dossier attach.
No HTML scraping; no invented line items.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from pathlib import Path
from typing import Any

_log = logging.getLogger("atlas.investment.company_documents")

VERSION = "iip.4.company_documents"
STORE_REL = Path("investment") / "company_documents"
IMPORT_DROP_REL = Path("imports") / "company_documents"
DEFAULT_PROGRAM = "market_intelligence"

KIND_ALIASES: dict[str, str] = {
    "annual": "annual",
    "ar": "annual",
    "annual_report": "annual",
    "fy": "annual",
    "quarterly": "quarterly",
    "results": "quarterly",
    "q": "quarterly",
    "presentation": "presentation",
    "investor_presentation": "presentation",
    "deck": "deck",
    "slides": "deck",
    "transcript": "transcript",
    "call": "earnings_call",
    "conference_call": "earnings_call",
    "earnings_call": "earnings_call",
}

CLAIM_SECTIONS: dict[str, tuple[str, ...]] = {
    "guidance": ("growth", "thesis"),
    "risk": ("risks", "management"),
    "kpi": ("growth", "profitability", "financial_health"),
    "cash": ("cash_flow", "valuation"),
    "governance": ("management", "risks"),
}


def store_dir(data_dir: str | Path, program_id: str = DEFAULT_PROGRAM) -> Path:
    safe = re.sub(r"[^a-zA-Z0-9_\-]+", "_", program_id or DEFAULT_PROGRAM)
    return Path(data_dir) / STORE_REL / safe


def import_drop_dir(data_dir: str | Path) -> Path:
    return Path(data_dir) / IMPORT_DROP_REL


def normalize_symbol(symbol: str) -> str:
    s = (symbol or "").strip().upper()
    if not s:
        return ""
    if s.endswith(".BO"):
        return s
    if not s.endswith(".NS") and "." not in s:
        return f"{s}.NS"
    return s


def normalize_kind(kind: str | None) -> str:
    k = (kind or "annual").strip().lower().replace(" ", "_")
    return KIND_ALIASES.get(k, k if k else "annual")


def parse_drop_filename(name: str) -> dict[str, str] | None:
    """``SYMBOL__kind__period.ext`` or ``SYMBOL__kind.ext``."""
    stem = Path(name).stem
    parts = [p for p in stem.split("__") if p]
    if len(parts) < 2:
        # Fallback: SYMBOL_kind.pdf
        m = re.match(r"^([A-Za-z0-9.\-]+)[_-](annual|ar|quarterly|deck|transcript|presentation|call)", stem, re.I)
        if not m:
            return None
        return {
            "symbol": normalize_symbol(m.group(1)),
            "kind": normalize_kind(m.group(2)),
            "period": "",
        }
    return {
        "symbol": normalize_symbol(parts[0]),
        "kind": normalize_kind(parts[1]),
        "period": parts[2] if len(parts) > 2 else "",
    }


def read_document_text(path: Path, *, ocr_enabled: bool = True) -> dict[str, Any]:
    """Extract text from PDF/TXT using ingestion extractors + optional Research OCR."""
    path = Path(path)
    if not path.is_file():
        return {
            "outcome": "missing",
            "text": "",
            "method": "none",
            "chars": 0,
            "note": f"file not found: {path}",
        }
    suffix = path.suffix.lower()
    if suffix in {".txt", ".md", ".html", ".htm"}:
        try:
            text = path.read_text(encoding="utf-8", errors="replace").strip()
        except Exception as exc:  # noqa: BLE001
            return {"outcome": "error", "text": "", "method": "text", "chars": 0, "note": str(exc)[:200]}
        return {
            "outcome": "ok" if text else "empty",
            "text": text,
            "method": "text",
            "chars": len(text),
            "note": "" if text else "empty text file",
        }

    text = ""
    method = "none"
    try:
        from atlas.ingestion.extractors import extract as extract_file

        text = (extract_file(path) or "").strip()
        if text:
            method = "pdf_text_layer" if suffix == ".pdf" else "extract"
    except Exception as exc:  # noqa: BLE001
        _log.debug("text-layer extract failed for %s", path, exc_info=True)
        return {
            "outcome": "error",
            "text": "",
            "method": "pdf_text_layer",
            "chars": 0,
            "note": str(exc)[:200],
        }

    if len(text) < 200 and suffix == ".pdf" and ocr_enabled:
        try:
            from atlas.research.pdf_ocr import ocr_pdf

            ocr = ocr_pdf(path)
            ocr_text = ""
            if isinstance(ocr, dict):
                ocr_text = str(ocr.get("text") or "").strip()
            elif hasattr(ocr, "text"):
                ocr_text = str(getattr(ocr, "text") or "").strip()
            if len(ocr_text) > len(text):
                text = ocr_text
                method = "pdf_ocr"
        except Exception:  # noqa: BLE001
            _log.debug("OCR skipped for %s", path, exc_info=True)

    if not text:
        return {
            "outcome": "empty",
            "text": "",
            "method": method or "none",
            "chars": 0,
            "note": "No extractable text (scanned PDF or empty). CapabilityGap until OCR/text available.",
        }
    return {"outcome": "ok", "text": text, "method": method, "chars": len(text), "note": ""}


def _snippet(text: str, start: int, *, radius: int = 160) -> str:
    a = max(0, start - 40)
    b = min(len(text), start + radius)
    snip = re.sub(r"\s+", " ", text[a:b]).strip()
    return snip[:220]


def extract_company_claims(text: str, *, limit: int = 24) -> list[dict[str, Any]]:
    """Deterministic guidance / risk / KPI claims — never invent missing numbers."""
    if not text or not text.strip():
        return []
    body = text
    claims: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _add(kind: str, claim: str, *, section_hint: str, confidence: str = "low") -> None:
        key = f"{kind}:{claim[:80].lower()}"
        if key in seen or not claim.strip():
            return
        seen.add(key)
        claims.append(
            {
                "kind": kind,
                "claim": claim.strip()[:280],
                "section_hint": section_hint,
                "confidence": confidence,
                "status": "present",
            }
        )

    # Guidance / outlook sentences
    for m in re.finditer(
        r"(?i)([^.!?\n]{0,40}\b(?:guidance|outlook|we expect|management expects|expects to|"
        r"target(?:s)?|forecast)\b[^.!?\n]{10,180}[.!?])",
        body,
    ):
        _add("guidance", m.group(1).strip(), section_hint="growth")
        if len(claims) >= limit:
            return claims[:limit]

    # Risk sentences
    for m in re.finditer(
        r"(?i)([^.!?\n]{0,30}\b(?:key risks?|risk factors?|risks include|material risk|"
        r"downside|headwind[s]?)\b[^.!?\n]{10,180}[.!?])",
        body,
    ):
        _add("risk", m.group(1).strip(), section_hint="risks")
        if len(claims) >= limit:
            return claims[:limit]

    # KPI / ratio patterns
    kpi_patterns: list[tuple[str, str, str]] = [
        (r"(?i)\bROE\b[^0-9%]{0,12}(\d+(?:\.\d+)?)\s*%?", "roe", "financial_health"),
        (r"(?i)\bROCE\b[^0-9%]{0,12}(\d+(?:\.\d+)?)\s*%?", "roce", "financial_health"),
        (r"(?i)\bROIC\b[^0-9%]{0,12}(\d+(?:\.\d+)?)\s*%?", "roic", "financial_health"),
        (
            r"(?i)\bdebt[\s\-]*to[\s\-]*equity\b[^0-9]{0,12}(\d+(?:\.\d+)?)",
            "debt_to_equity",
            "financial_health",
        ),
        (r"(?i)\boperating margin\b[^0-9%]{0,12}(\d+(?:\.\d+)?)\s*%?", "operating_margin", "profitability"),
        (r"(?i)\bnet margin\b[^0-9%]{0,12}(\d+(?:\.\d+)?)\s*%?", "net_margin", "profitability"),
        (r"(?i)\brevenue growth\b[^0-9%]{0,12}(\d+(?:\.\d+)?)\s*%?", "revenue_growth_yoy", "growth"),
        (r"(?i)\bsales growth\b[^0-9%]{0,12}(\d+(?:\.\d+)?)\s*%?", "revenue_growth_yoy", "growth"),
        (r"(?i)\bpromoter holding\b[^0-9%]{0,12}(\d+(?:\.\d+)?)\s*%?", "promoter_holding", "management"),
        (r"(?i)\bFCF\b[^0-9]{0,16}(\d+(?:\.\d+)?)", "fcf", "cash_flow"),
        (r"(?i)\bfree cash flow\b[^0-9]{0,16}(\d+(?:\.\d+)?)", "fcf", "cash_flow"),
    ]
    for pat, field, sec in kpi_patterns:
        m = re.search(pat, body)
        if not m:
            continue
        val = m.group(1)
        snip = _snippet(body, m.start())
        _add(
            "kpi",
            f"{field.replace('_', ' ')} ≈ {val} — «{snip}»",
            section_hint=sec,
            confidence="low",
        )
        claims[-1]["field"] = field
        try:
            claims[-1]["value"] = float(val)
        except ValueError:
            pass
        if len(claims) >= limit:
            break

    return claims[:limit]


def claims_to_snapshot_fields(claims: list[dict[str, Any]]) -> dict[str, Any]:
    """Map confidently parsed KPI claims to operator-snapshot style fields."""
    out: dict[str, Any] = {}
    for c in claims:
        field = c.get("field")
        val = c.get("value")
        if not field or val is None:
            continue
        # Store percent-like KPIs as percent numbers (fundamentals convention)
        if field in {
            "roe",
            "roce",
            "roic",
            "operating_margin",
            "net_margin",
            "revenue_growth_yoy",
            "promoter_holding",
        }:
            out[field] = float(val)
        elif field == "debt_to_equity":
            out["debt_to_equity"] = float(val)
        elif field == "fcf":
            out["fcf"] = float(val)
        if field == "revenue_growth_yoy":
            out.setdefault("revenue_cagr", float(val))
        if field == "roce" and "roic" not in out:
            out["roic"] = float(val)
    return out


def _doc_id(symbol: str, kind: str, path: Path | None, content_hash: str) -> str:
    base = f"{symbol}_{kind}_{content_hash[:12]}"
    return re.sub(r"[^a-zA-Z0-9_\-]+", "_", base)


def _content_hash(data: bytes | str) -> str:
    raw = data.encode("utf-8") if isinstance(data, str) else data
    return hashlib.sha256(raw).hexdigest()


def save_manifest(
    data_dir: str | Path,
    manifest: dict[str, Any],
    *,
    program_id: str = DEFAULT_PROGRAM,
) -> Path | None:
    sym = normalize_symbol(str(manifest.get("symbol") or ""))
    if not sym or not data_dir:
        return None
    root = store_dir(data_dir, program_id) / sym
    root.mkdir(parents=True, exist_ok=True)
    doc_id = str(manifest.get("doc_id") or _doc_id(sym, str(manifest.get("kind")), None, "x"))
    path = root / f"{doc_id}.json"
    manifest = dict(manifest)
    manifest["doc_id"] = doc_id
    manifest["symbol"] = sym
    manifest["version"] = VERSION
    manifest["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    # index
    index_path = store_dir(data_dir, program_id) / "index.json"
    try:
        index = {"documents": [], "version": VERSION}
        if index_path.is_file():
            index = json.loads(index_path.read_text(encoding="utf-8"))
        docs = [d for d in (index.get("documents") or []) if d.get("doc_id") != doc_id]
        docs.insert(
            0,
            {
                "doc_id": doc_id,
                "symbol": sym,
                "kind": manifest.get("kind"),
                "as_of": manifest.get("as_of"),
                "claims_count": len(manifest.get("claims") or []),
                "path": str(path),
                "outcome": manifest.get("read_outcome"),
            },
        )
        index["documents"] = docs[:200]
        index["count"] = len(docs)
        index["updated_at"] = manifest["updated_at"]
        index_path.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    except Exception:  # noqa: BLE001
        _log.debug("index update failed", exc_info=True)
    return path


def list_documents(
    data_dir: str | Path | None,
    *,
    program_id: str = DEFAULT_PROGRAM,
    symbol: str | None = None,
    limit: int = 40,
) -> dict[str, Any]:
    if not data_dir:
        return {"documents": [], "count": 0, "drop_dir": None, "version": VERSION}
    drop = import_drop_dir(data_dir)
    index_path = store_dir(data_dir, program_id) / "index.json"
    docs: list[dict[str, Any]] = []
    if index_path.is_file():
        try:
            raw = json.loads(index_path.read_text(encoding="utf-8"))
            docs = list(raw.get("documents") or [])
        except Exception:  # noqa: BLE001
            docs = []
    if symbol:
        sym = normalize_symbol(symbol)
        docs = [d for d in docs if d.get("symbol") == sym]
    return {
        "documents": docs[: max(1, int(limit))],
        "count": len(docs),
        "drop_dir": str(drop),
        "store_dir": str(store_dir(data_dir, program_id)),
        "version": VERSION,
        "guide": (
            "Drop files as SYMBOL__kind__period.pdf (e.g. INFY__annual__FY25.pdf). "
            "Kinds: annual, quarterly, deck, presentation, transcript, earnings_call. "
            "No HTML scraping — operator upload only."
        ),
    }


def ingest_path(
    data_dir: str | Path | None,
    path: str | Path,
    *,
    symbol: str,
    kind: str = "annual",
    program_id: str = DEFAULT_PROGRAM,
    as_of: str | None = None,
    period: str = "",
    note: str = "",
    title: str = "",
    ocr_enabled: bool = True,
    text_override: str | None = None,
) -> dict[str, Any]:
    """Read + extract + persist manifest (IRA attach is caller's job or push flag)."""
    sym = normalize_symbol(symbol)
    kind_n = normalize_kind(kind)
    src = Path(path) if path else None
    if text_override is not None:
        read = {
            "outcome": "ok" if text_override.strip() else "empty",
            "text": text_override,
            "method": "override",
            "chars": len(text_override or ""),
            "note": "",
        }
        content_hash = _content_hash(text_override)
        source_path = str(src) if src else None
    else:
        if not src or not src.is_file():
            return {"ok": False, "reason": "missing_file", "path": str(path)}
        read = read_document_text(src, ocr_enabled=ocr_enabled)
        try:
            content_hash = _content_hash(src.read_bytes())
        except Exception:  # noqa: BLE001
            content_hash = _content_hash(read.get("text") or "")
        source_path = str(src.resolve())

    claims = extract_company_claims(str(read.get("text") or ""))
    fields = claims_to_snapshot_fields(claims)
    doc_id = _doc_id(sym, kind_n, src, content_hash)
    title_n = title or (
        f"{kind_n.replace('_', ' ').title()} — {sym}"
        + (f" ({period})" if period else "")
    )
    as_of_n = as_of or time.strftime("%Y-%m-%d", time.gmtime())
    manifest = {
        "doc_id": doc_id,
        "symbol": sym,
        "kind": kind_n,
        "title": title_n,
        "as_of": as_of_n,
        "period": period,
        "note": note,
        "source_path": source_path,
        "content_hash": content_hash,
        "read_outcome": read.get("outcome"),
        "read_method": read.get("method"),
        "chars": read.get("chars"),
        "read_note": read.get("note"),
        "claims": claims,
        "claims_count": len(claims),
        "snapshot_fields": fields,
        "program_id": program_id,
        "version": VERSION,
    }
    saved = None
    if data_dir:
        saved = save_manifest(data_dir, manifest, program_id=program_id)
    return {
        "ok": read.get("outcome") in {"ok", "empty"},
        "manifest": manifest,
        "path": str(saved) if saved else None,
        "claims_count": len(claims),
        "snapshot_fields": fields,
        "read": {k: read.get(k) for k in ("outcome", "method", "chars", "note")},
    }


def import_drop_folder(
    data_dir: str | Path | None,
    *,
    program_id: str = DEFAULT_PROGRAM,
    ocr_enabled: bool = True,
) -> dict[str, Any]:
    if not data_dir:
        return {"imported": 0, "files": [], "note": "no data_dir"}
    root = import_drop_dir(data_dir)
    root.mkdir(parents=True, exist_ok=True)
    done = root / "done"
    done.mkdir(parents=True, exist_ok=True)
    files_out: list[dict[str, Any]] = []
    total = 0
    for path in sorted(root.iterdir()):
        if not path.is_file():
            continue
        if path.suffix.lower() not in {".pdf", ".txt", ".md"}:
            continue
        meta = parse_drop_filename(path.name)
        if not meta:
            files_out.append(
                {
                    "file": path.name,
                    "error": "filename must be SYMBOL__kind__period.ext",
                }
            )
            continue
        try:
            result = ingest_path(
                data_dir,
                path,
                symbol=meta["symbol"],
                kind=meta["kind"],
                period=meta.get("period") or "",
                program_id=program_id,
                note=f"drop:{path.name}",
                ocr_enabled=ocr_enabled,
            )
            total += 1 if result.get("ok") else 0
            dest = done / path.name
            path.replace(dest)
            files_out.append(
                {
                    "file": path.name,
                    "symbol": meta["symbol"],
                    "kind": meta["kind"],
                    "claims": result.get("claims_count"),
                    "moved_to": str(dest),
                    "doc_id": (result.get("manifest") or {}).get("doc_id"),
                }
            )
        except Exception as exc:  # noqa: BLE001
            files_out.append({"file": path.name, "error": str(exc)[:200]})
    return {
        "imported": total,
        "files": files_out,
        "drop_dir": str(root),
        "version": VERSION,
    }


def documents_view(
    data_dir: str | Path | None,
    *,
    program_id: str = DEFAULT_PROGRAM,
    limit: int = 25,
) -> dict[str, Any]:
    return list_documents(data_dir, program_id=program_id, limit=limit)
