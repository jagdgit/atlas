"""LI.1a — Market Laboratory identity and hermetic isolation helpers.

A Laboratory contains a ledger (among other subsystems). ``laboratory_id`` is a
1:1 alias of IL.10 ``portfolio_key``. Every LI feature must refuse to pool
statistics, priors, cash, experiments, or outcome labels across laboratories.
"""

from __future__ import annotations

from typing import Any, Iterable

VERSION = "li.1a.laboratory"

DEFAULT_SWING_LAB = "india_equity_learner"
DEFAULT_INTRADAY_LAB = "equity_intraday_learner"
DEFAULT_FNO_LAB = "india_fno_learner"
DEFAULT_EXPERIMENT_ID = "default"

# Operator mail / hourly board — three paper laboratories, never pooled P&L.
MAIL_SNAPSHOT_LABS: tuple[str, ...] = (
    DEFAULT_SWING_LAB,
    DEFAULT_FNO_LAB,
    DEFAULT_INTRADAY_LAB,
)
MAIL_LAB_TITLES: dict[str, str] = {
    DEFAULT_SWING_LAB: "India equity (swing)",
    DEFAULT_FNO_LAB: "NIFTY index-proxy (F&O lab)",
    DEFAULT_INTRADAY_LAB: "India equity (intraday 5m)",
}

# Transfer classes (world may cross labs; strategy/returns must not).
TRANSFER_WORLD = "world"
TRANSFER_STRATEGY = "strategy"
TRANSFER_RETURNS = "returns"


class LaboratoryContaminationError(ValueError):
    """Raised when a call would mix laboratories' outcome stats or labels."""


def normalize_laboratory_id(
    laboratory_id: str | None = None,
    *,
    portfolio_key: str | None = None,
    default: str = DEFAULT_SWING_LAB,
) -> str:
    """Resolve laboratory_id; portfolio_key is an accepted synonym (1:1)."""
    for raw in (laboratory_id, portfolio_key):
        s = str(raw or "").strip()
        if s:
            return s
    return str(default or DEFAULT_SWING_LAB).strip() or DEFAULT_SWING_LAB


def laboratory_id_for(portfolio_key: str | None) -> str:
    return normalize_laboratory_id(portfolio_key=portfolio_key)


def portfolio_key_for(laboratory_id: str | None) -> str:
    """Inverse alias — ledger / IL.10 key equals laboratory_id in LI.1a."""
    return normalize_laboratory_id(laboratory_id=laboratory_id)


def experience_tag(laboratory_id: str) -> str:
    """Lab-scoped experience tag (same string as portfolio:{key} for IL.10 compat)."""
    lid = normalize_laboratory_id(laboratory_id=laboratory_id)
    return f"portfolio:{lid}"


def laboratory_tag(laboratory_id: str) -> str:
    """Explicit laboratory tag for new journals (also keep portfolio: tag)."""
    lid = normalize_laboratory_id(laboratory_id=laboratory_id)
    return f"laboratory:{lid}"


def lab_prior_tag(laboratory_id: str) -> str:
    lid = normalize_laboratory_id(laboratory_id=laboratory_id)
    return f"lab:{lid}"


def stamp_laboratory_identity(doc: dict[str, Any], laboratory_id: str | None = None) -> dict[str, Any]:
    """Ensure portfolio_key and laboratory_id agree on ``doc`` (mutates + returns)."""
    lid = normalize_laboratory_id(
        laboratory_id=laboratory_id or doc.get("laboratory_id"),
        portfolio_key=doc.get("portfolio_key"),
    )
    doc["laboratory_id"] = lid
    doc["portfolio_key"] = lid
    return doc


def extract_laboratory_id(row: dict[str, Any] | None) -> str | None:
    if not isinstance(row, dict):
        return None
    for key in ("laboratory_id", "portfolio_key"):
        v = row.get(key)
        if v:
            return str(v).strip()
    payload = row.get("payload")
    if isinstance(payload, dict):
        for key in ("laboratory_id", "portfolio_key"):
            v = payload.get(key)
            if v:
                return str(v).strip()
        extra = payload.get("extra")
        if isinstance(extra, dict):
            for key in ("laboratory_id", "portfolio_key"):
                v = extra.get(key)
                if v:
                    return str(v).strip()
    return None


def distinct_laboratories(rows: Iterable[dict[str, Any] | None]) -> list[str]:
    seen: list[str] = []
    for row in rows:
        lid = extract_laboratory_id(row)
        if lid and lid not in seen:
            seen.append(lid)
    return seen


def assert_single_laboratory(
    rows: Iterable[dict[str, Any] | None],
    *,
    expected: str | None = None,
    context: str = "batch",
) -> str | None:
    """Return the sole laboratory_id, or raise if multiple / mismatch.

    Empty batches return ``expected`` (or None) — no contamination possible.
    """
    labs = distinct_laboratories(rows)
    if not labs:
        return normalize_laboratory_id(laboratory_id=expected) if expected else None
    if len(labs) > 1:
        raise LaboratoryContaminationError(
            f"laboratory hermeticity violated in {context}: mixed {labs} "
            f"(statistics/priors/outcome labels must never pool across laboratories)"
        )
    sole = labs[0]
    if expected and sole != normalize_laboratory_id(laboratory_id=expected):
        raise LaboratoryContaminationError(
            f"laboratory hermeticity violated in {context}: "
            f"expected {expected!r}, found {sole!r}"
        )
    return sole


def refuse_pooled_edge_metrics(
    rows: Iterable[dict[str, Any] | None],
    *,
    context: str = "edge_metrics",
) -> str | None:
    """Guard before computing win_rate / expectancy — fail closed on mix."""
    return assert_single_laboratory(rows, context=context)


def normalize_experiment_id(experiment_id: str | None = None) -> str:
    """LI.4 — experiments default to ``default`` so legacy rows still gate."""
    s = str(experiment_id or "").strip()
    return s or DEFAULT_EXPERIMENT_ID


def extract_strategy_tag(row: dict[str, Any] | None) -> str:
    if not isinstance(row, dict):
        return "unknown"
    if row.get("strategy_tag"):
        return str(row["strategy_tag"]).strip() or "unknown"
    payload = row.get("payload")
    if isinstance(payload, dict):
        if payload.get("strategy_tag"):
            return str(payload["strategy_tag"]).strip() or "unknown"
        extra = payload.get("extra")
        if isinstance(extra, dict) and extra.get("strategy_tag"):
            return str(extra["strategy_tag"]).strip() or "unknown"
    return "unknown"


def extract_experiment_id(row: dict[str, Any] | None) -> str:
    if not isinstance(row, dict):
        return DEFAULT_EXPERIMENT_ID
    if row.get("experiment_id"):
        return normalize_experiment_id(str(row["experiment_id"]))
    payload = row.get("payload")
    if isinstance(payload, dict):
        if payload.get("experiment_id"):
            return normalize_experiment_id(str(payload["experiment_id"]))
        extra = payload.get("extra")
        if isinstance(extra, dict) and extra.get("experiment_id"):
            return normalize_experiment_id(str(extra["experiment_id"]))
    return DEFAULT_EXPERIMENT_ID


def lane_key(
    laboratory_id: str | None = None,
    strategy_tag: str | None = None,
    experiment_id: str | None = None,
    *,
    portfolio_key: str | None = None,
) -> str:
    """LI.4 — sample-gate / edge lane: ``lab|strategy|experiment``."""
    lab = normalize_laboratory_id(
        laboratory_id=laboratory_id, portfolio_key=portfolio_key
    )
    tag = str(strategy_tag or "").strip() or "unknown"
    exp = normalize_experiment_id(experiment_id)
    return f"{lab}|{tag}|{exp}"


def parse_lane_key(key: str) -> dict[str, str]:
    parts = str(key or "").split("|")
    if len(parts) == 3:
        return {
            "laboratory_id": parts[0],
            "strategy_tag": parts[1],
            "experiment_id": parts[2],
        }
    if len(parts) == 1 and parts[0]:
        # Legacy DI.7 key = strategy_tag only
        return {
            "laboratory_id": "",
            "strategy_tag": parts[0],
            "experiment_id": DEFAULT_EXPERIMENT_ID,
        }
    return {
        "laboratory_id": parts[0] if parts else "",
        "strategy_tag": parts[1] if len(parts) > 1 else "unknown",
        "experiment_id": normalize_experiment_id(parts[2] if len(parts) > 2 else None),
    }


def lane_display_key(
    strategy_tag: str | None = None,
    experiment_id: str | None = None,
) -> str:
    """Dashboard lane label within a single lab (omit default experiment)."""
    tag = str(strategy_tag or "").strip() or "unknown"
    exp = normalize_experiment_id(experiment_id)
    if exp == DEFAULT_EXPERIMENT_ID:
        return tag
    return f"{tag}@{exp}"


def resolve_lane_from_rows(
    attr: dict[str, Any] | None,
    packet: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Resolve laboratory / strategy / experiment from attribution + packet."""
    lab = (
        extract_laboratory_id(packet)
        or extract_laboratory_id(attr)
        or DEFAULT_SWING_LAB
    )
    tag = "unknown"
    if isinstance(packet, dict) and packet.get("strategy_tag"):
        tag = str(packet["strategy_tag"]).strip() or "unknown"
    else:
        tag = extract_strategy_tag(attr)
    exp = DEFAULT_EXPERIMENT_ID
    if isinstance(packet, dict) and packet.get("experiment_id"):
        exp = normalize_experiment_id(str(packet["experiment_id"]))
    else:
        exp = extract_experiment_id(attr)
    return {
        "laboratory_id": lab,
        "strategy_tag": tag,
        "experiment_id": exp,
        "lane_key": lane_key(lab, tag, exp),
        "display_key": lane_display_key(tag, exp),
    }


def transfer_allowed(transfer_class: str) -> bool:
    """World facts may cross labs; strategy/returns must not."""
    tc = str(transfer_class or "").strip().lower()
    if tc == TRANSFER_WORLD:
        return True
    if tc in {TRANSFER_STRATEGY, TRANSFER_RETURNS, "priors", "win_rate", "expectancy"}:
        return False
    return False
