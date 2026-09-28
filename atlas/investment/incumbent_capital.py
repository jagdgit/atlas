"""OI-ICR0 — Incumbent capital safety gates (swing lab).

Technical BUY ≠ capital permission. Until Allocation Comparison Packets (ICR.1)
exist, swing ADDs are frozen; AVOID / QUARANTINED block BUY and ADD.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

VERSION = "icr.0.v1"

REASON_ADD_BLOCKED_RESEARCH = "add_blocked_research"
REASON_ADD_BLOCKED_QUARANTINE = "add_blocked_quarantine"
REASON_ADD_BLOCKED_NO_ACP = "add_blocked_no_acp"
REASON_ADD_BLOCKED_DUPLICATE_STATE = "add_blocked_duplicate_state"
REASON_BUY_BLOCKED_RESEARCH = "buy_blocked_research"
REASON_BUY_BLOCKED_QUARANTINE = "buy_blocked_quarantine"

_ACP_DECISIONS_ALLOW_ADD = frozenset({"ADD"})


def icr0_enabled(cfg: dict[str, Any] | None, laboratory_id: str | None) -> bool:
    """Swing-lab default on; FNO/intraday off unless explicitly enabled."""
    cfg = cfg or {}
    if cfg.get("icr0_enabled") is False:
        return False
    if cfg.get("icr0_enabled") is True:
        return True
    try:
        from atlas.investment.lab_contracts import LAB_SWING, lab_kind

        return lab_kind(laboratory_id, cfg=cfg) == LAB_SWING
    except Exception:  # noqa: BLE001
        pk = str(laboratory_id or "").lower()
        return "equity_learner" in pk or pk in {"india_equity_learner", "equity_swing_learner"}


def _thesis_stance(awareness: dict[str, Any] | None) -> str:
    try:
        from atlas.investment.lab_contracts import thesis_stance_from_awareness

        return str(thesis_stance_from_awareness(awareness) or "ABSENT").upper()
    except Exception:  # noqa: BLE001
        return "ABSENT"


def _identity_row(symbol: str, awareness: dict[str, Any] | None) -> dict[str, Any]:
    try:
        from atlas.investment.thesis_identity import validate_thesis_identity

        return validate_thesis_identity(symbol, awareness if isinstance(awareness, dict) else None)
    except Exception:  # noqa: BLE001
        return {"identity": "UNKNOWN"}


def allocation_state_hash(
    *,
    laboratory_id: str,
    symbol: str,
    held: float,
    stance: str,
    identity: str,
    extra: dict[str, Any] | None = None,
) -> str:
    """Fingerprint for same-state = same experiment (ICR.0 stub; densify in ICR.1)."""
    payload = {
        "lab": str(laboratory_id or ""),
        "symbol": str(symbol or "").upper(),
        "held_open": float(held or 0) > 1e-12,
        "stance": str(stance or "").upper(),
        "identity": str(identity or "").upper(),
        "extra": extra or {},
        "v": VERSION,
    }
    raw = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def acp_path(data_dir: str | Path, laboratory_id: str, symbol: str, state_hash: str) -> Path:
    lab = str(laboratory_id or "unknown").strip() or "unknown"
    sym = str(symbol or "UNKNOWN").strip().upper() or "UNKNOWN"
    return (
        Path(data_dir)
        / "investment"
        / "allocation"
        / lab
        / f"{sym}_{state_hash}.json"
    )


def acp_day_registry_path(
    data_dir: str | Path, laboratory_id: str, as_of_ist: str
) -> Path:
    lab = str(laboratory_id or "unknown").strip() or "unknown"
    day = str(as_of_ist or "")[:10]
    return Path(data_dir) / "investment" / "allocation" / lab / f"decisions_{day}.json"


def load_acp_day_registry(
    data_dir: str | Path | None, laboratory_id: str, as_of_ist: str
) -> dict[str, Any]:
    if not data_dir:
        return {"version": VERSION, "as_of_ist": as_of_ist, "state_hashes": {}}
    path = acp_day_registry_path(data_dir, laboratory_id, as_of_ist)
    if not path.is_file():
        return {"version": VERSION, "as_of_ist": as_of_ist[:10], "state_hashes": {}}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(doc, dict):
            doc.setdefault("state_hashes", {})
            return doc
    except Exception:  # noqa: BLE001
        pass
    return {"version": VERSION, "as_of_ist": as_of_ist[:10], "state_hashes": {}}


def register_acp_decision_today(
    data_dir: str | Path | None,
    *,
    laboratory_id: str,
    state_hash: str,
    symbol: str,
    decision: str,
    as_of_ist: str,
) -> dict[str, Any]:
    """EXP0 / ICR.4 — one ACP decision per state_hash per IST day.

    Returns ``{first: bool, prior: dict|None}``. ``first=False`` means same
    state already decided today (reuse prior decision; do not invent a new ADD).
    """
    day = str(as_of_ist or "")[:10]
    sh = str(state_hash or "")
    if not data_dir or not sh:
        return {"first": True, "prior": None}
    reg = load_acp_day_registry(data_dir, laboratory_id, day)
    hashes = reg.setdefault("state_hashes", {})
    prior = hashes.get(sh) if isinstance(hashes.get(sh), dict) else None
    if prior:
        return {"first": False, "prior": prior}
    entry = {
        "symbol": str(symbol or "").upper(),
        "decision": str(decision or ""),
        "registered_at": __import__("time").strftime(
            "%Y-%m-%dT%H:%M:%SZ", __import__("time").gmtime()
        ),
    }
    hashes[sh] = entry
    path = acp_day_registry_path(data_dir, laboratory_id, day)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(reg, indent=2), encoding="utf-8")
    except OSError:
        pass
    return {"first": True, "prior": None}


def load_acp(
    data_dir: str | Path | None,
    *,
    laboratory_id: str,
    symbol: str,
    state_hash: str,
) -> dict[str, Any] | None:
    """ICR.1 will persist ACPs; ICR.0 returns None when missing."""
    if not data_dir:
        return None
    path = acp_path(data_dir, laboratory_id, symbol, state_hash)
    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else None
    except Exception:  # noqa: BLE001
        return None


def acp_allows_add(acp: dict[str, Any] | None) -> bool:
    if not isinstance(acp, dict):
        return False
    decision = str(acp.get("decision") or "").upper()
    return decision in _ACP_DECISIONS_ALLOW_ADD


def evaluate_icr0_buy(
    *,
    laboratory_id: str,
    symbol: str,
    held: float,
    awareness: dict[str, Any] | None,
    cfg: dict[str, Any] | None = None,
    data_dir: str | Path | None = None,
    seen_state_hashes: set[str] | None = None,
) -> dict[str, Any]:
    """Gate a swing BUY/ADD. Returns ``allowed`` + reason codes (never auto-sells)."""
    cfg = cfg or {}
    sym = str(symbol or "").strip().upper()
    out: dict[str, Any] = {
        "version": VERSION,
        "allowed": True,
        "reason_code": None,
        "line": None,
        "is_add": float(held or 0) > 1e-12,
        "stance": None,
        "identity": None,
        "state_hash": None,
    }
    if not icr0_enabled(cfg, laboratory_id):
        return out
    if not sym:
        return out

    stance = _thesis_stance(awareness)
    ident_row = _identity_row(sym, awareness)
    identity = str(ident_row.get("identity") or "UNKNOWN").upper()
    state_hash = allocation_state_hash(
        laboratory_id=laboratory_id,
        symbol=sym,
        held=float(held or 0),
        stance=stance,
        identity=identity,
    )
    out["stance"] = stance
    out["identity"] = identity
    out["state_hash"] = state_hash
    is_add = float(held or 0) > 1e-12
    out["is_add"] = is_add

    if identity in {"QUARANTINED"}:
        code = REASON_ADD_BLOCKED_QUARANTINE if is_add else REASON_BUY_BLOCKED_QUARANTINE
        out.update(
            allowed=False,
            reason_code=code,
            line=f"{sym}: {code} (identity=QUARANTINED)",
        )
        return out

    if stance in {"AVOID", "INVALID"}:
        code = REASON_ADD_BLOCKED_RESEARCH if is_add else REASON_BUY_BLOCKED_RESEARCH
        out.update(
            allowed=False,
            reason_code=code,
            line=f"{sym}: {code} (thesis={stance})",
        )
        return out

    if is_add:
        acp = load_acp(
            data_dir,
            laboratory_id=str(laboratory_id),
            symbol=sym,
            state_hash=state_hash,
        )
        if not acp_allows_add(acp):
            out.update(
                allowed=False,
                reason_code=REASON_ADD_BLOCKED_NO_ACP,
                line=(
                    f"{sym}: {REASON_ADD_BLOCKED_NO_ACP} "
                    "(incumbent ADD requires Allocation Comparison Packet)"
                ),
            )
            return out
        if seen_state_hashes is not None and state_hash in seen_state_hashes:
            out.update(
                allowed=False,
                reason_code=REASON_ADD_BLOCKED_DUPLICATE_STATE,
                line=f"{sym}: {REASON_ADD_BLOCKED_DUPLICATE_STATE} (state_hash={state_hash})",
            )
            return out

    return out
