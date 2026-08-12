"""DAV densify — sector Yahoo index benchmarks for relative strength.

Maps SI sector packs / free-text sector labels → Yahoo chart symbols.
Never invents RS; callers must fetch bars. Falls back to NIFTY (^NSEI).
"""

from __future__ import annotations

from typing import Any

NIFTY_BENCHMARK_YAHOO = "^NSEI"

# Pack id / keyword → Yahoo India sector index (best-effort public symbols).
PACK_TO_YAHOO_INDEX: dict[str, str] = {
    "banks": "^NSEBANK",
    "saas_it": "^CNXIT",
    "pharma": "^CNXPHARMA",
    "healthcare": "^CNXPHARMA",  # closest liquid proxy
    "defence": "^CNXINFRA",  # no dedicated defence index — infra/defence-adjacent
    "manufacturing": "^CNXAUTO",  # auto/industrial tilt; better than broad NIFTY alone
}

_SECTOR_KEYWORD_TO_INDEX: tuple[tuple[tuple[str, ...], str], ...] = (
    (("bank", "nbfc", "financial"), "^NSEBANK"),
    (("it ", "software", "information technology", "saas"), "^CNXIT"),
    (("pharma", "drug"), "^CNXPHARMA"),
    (("hospital", "health care", "healthcare", "diagnostic"), "^CNXPHARMA"),
    (("auto", "automobile", "two wheeler", "oem"), "^CNXAUTO"),
    (("fmcg", "consumer staple", "consumer durable", "paints"), "^CNXFMCG"),
    (("telecom", "telecommunication"), "^NSEI"),  # no liquid dedicated Yahoo proxy
    (("metal", "steel", "mining"), "^CNXMETAL"),
    (("energy", "oil", "gas", "power"), "^CNXENERGY"),
    (("realty", "real estate"), "^CNXREALTY"),
    (("infra", "infrastructure", "defence", "defense", "aerospace"), "^CNXINFRA"),
)


def yahoo_index_for_sector(
    *,
    pack_id: str | None = None,
    sector: str | None = None,
) -> str:
    """Resolve sector benchmark Yahoo symbol; default NIFTY when unknown."""
    pid = str(pack_id or "").strip().lower()
    if pid and pid in PACK_TO_YAHOO_INDEX:
        return PACK_TO_YAHOO_INDEX[pid]
    s = str(sector or "").strip().lower()
    if s:
        for keys, idx in _SECTOR_KEYWORD_TO_INDEX:
            if any(k in s for k in keys):
                return idx
    return NIFTY_BENCHMARK_YAHOO


def resolve_sector_benchmark(
    *,
    symbol: str | None = None,
    sector: str | None = None,
    pack_id: str | None = None,
    awareness: dict[str, Any] | None = None,
    fundamentals: dict[str, Any] | None = None,
    data_dir: str | None = None,
) -> dict[str, Any]:
    """Pick pack + Yahoo index for RS densify (honest fallback to NIFTY)."""
    aw = awareness if isinstance(awareness, dict) else {}
    fund = fundamentals if isinstance(fundamentals, dict) else {}
    thesis = aw.get("thesis") if isinstance(aw.get("thesis"), dict) else {}
    sec = (
        sector
        or aw.get("sector")
        or thesis.get("sector")
        or fund.get("sector")
        or fund.get("industry")
    )
    pid = pack_id or aw.get("pack") or aw.get("sector_pack_id")
    if not pid and (symbol or sec):
        try:
            from atlas.investment.research.sector_packs import pack_for

            pack = pack_for(
                str(symbol or ""),
                sector=str(sec) if sec else None,
                data_dir=data_dir,
            )
            if isinstance(pack, dict):
                pid = pack.get("id")
                if not sec:
                    sec = pack.get("label")
        except Exception:  # noqa: BLE001
            pass
    yahoo = yahoo_index_for_sector(
        pack_id=str(pid) if pid else None, sector=str(sec) if sec else None
    )
    return {
        "pack_id": pid,
        "sector": sec,
        "yahoo_symbol": yahoo,
        "is_broad_market": yahoo == NIFTY_BENCHMARK_YAHOO,
        "honesty": (
            "Sector RS uses Yahoo sector index when pack/sector known; "
            "else NIFTY (^NSEI). defence→CNXINFRA and healthcare→CNXPHARMA are proxies."
        ),
    }


def infer_event_regime_tags(
    *,
    title: str = "",
    detail: str = "",
    sectors: list[str] | None = None,
) -> list[str]:
    """Map policy/macro text → LQ.6 event regime tags. Never invent from P&L."""
    from atlas.investment.decision_packets import normalize_regime_tags

    blob = " ".join(
        [
            str(title or ""),
            str(detail or ""),
            " ".join(str(s) for s in (sectors or [])),
        ]
    ).lower()
    tags: list[str] = []
    if any(k in blob for k in ("election", "poll", "lok sabha", "assembly")):
        tags.append("election")
    if any(k in blob for k in ("budget", "union budget", "fiscal")):
        tags.append("budget")
    if any(k in blob for k in ("rate cut", "repo cut", "easing", "dovish")):
        tags.append("rate_cut")
    if any(k in blob for k in ("rate hike", "repo hike", "tightening", "hawkish")):
        tags.append("rate_hike")
    if any(
        k in blob
        for k in ("war", "geopolit", "sanction", "conflict", "missile", "border")
    ):
        tags.append("geopolitical")
    if any(k in blob for k in ("pandemic", "covid", "epidemic")):
        tags.append("pandemic")
    return normalize_regime_tags(tags)
