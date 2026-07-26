"""Sector Intelligence Packs + midcap hints for IRA (IRA.19 / next leap).

Hermetic operator aids — sector classification and research checklists only.
Never invents financial line items or MoS.

Each pack defines the business lens: KPIs, questions, failure modes,
valuation methods, moat, risks, management behaviors, falsifiers, drivers,
and evidence sources — so a hospital chain and a defence manufacturer
cannot produce twin theses.
"""

from __future__ import annotations

from typing import Any

from atlas.investment.research.models import normalize_symbol

# Public-knowledge midcap / large-cap hints (name/sector). Not fundamentals; not advice.
_SYMBOL_HINTS: dict[str, dict[str, Any]] = {
    "MTARTECH.NS": {
        "name": "MTAR Technologies",
        "sector": "Capital Goods",
        "subsector": "Precision engineering / aerospace & defence manufacturing",
        "pack": "defence",
        "facts": [
            "Indian precision engineering company oriented to aerospace, defence, and clean-energy hardware.",
            "Business quality hinges on order book, customer concentration (incl. ISRO/defence programs), "
            "and execution on specialised manufacturing.",
        ],
        "watch_items": [
            "Order book / customer concentration",
            "ISRO / defence program dependence",
            "Working capital and receivables cycle",
            "Execution / certification delays",
            "Capex intensity vs free cash flow",
        ],
        "source": "atlas_midcap_hint",
    },
    "APOLLOHOSP.NS": {
        "name": "Apollo Hospitals",
        "sector": "Healthcare",
        "subsector": "Hospital chain / healthcare services",
        "pack": "healthcare",
        "facts": [
            "Large Indian hospital network with brand recognition across metros and tier-2 cities.",
            "Economics driven by occupancy, ARPOB (average revenue per occupied bed), "
            "doctor retention, bed expansion, and payer / insurance mix.",
        ],
        "watch_items": [
            "Hospital occupancy",
            "ARPOB / case mix",
            "Doctor retention and utilization",
            "Bed expansion ROIC",
            "Insurance reimbursement / payer mix",
        ],
        "source": "atlas_midcap_hint",
    },
    "DIXON.NS": {
        "name": "Dixon Technologies",
        "sector": "Consumer Durables",
        "subsector": "EMS / electronics manufacturing",
        "pack": "manufacturing",
        "facts": [
            "Electronics manufacturing services (EMS) oriented business.",
        ],
        "watch_items": ["Customer concentration", "Gross margin durability", "Working capital"],
        "source": "atlas_midcap_hint",
    },
    "PERSISTENT.NS": {
        "name": "Persistent Systems",
        "sector": "Information Technology",
        "subsector": "IT services",
        "pack": "saas_it",
        "facts": ["Indian IT services / digital engineering company."],
        "watch_items": ["Deal pipeline", "Attrition", "Vertical mix"],
        "source": "atlas_midcap_hint",
    },
    "HDFCBANK.NS": {
        "name": "HDFC Bank",
        "sector": "Financial Services",
        "subsector": "Private sector bank",
        "pack": "banks",
        "facts": ["Large private sector bank — liability franchise and credit costs dominate quality."],
        "watch_items": ["NIM", "Slippages / credit cost", "CASA trend"],
        "source": "atlas_midcap_hint",
    },
    "ICICIBANK.NS": {
        "name": "ICICI Bank",
        "sector": "Financial Services",
        "subsector": "Private sector bank",
        "pack": "banks",
        "facts": ["Large private sector bank."],
        "watch_items": ["Asset quality", "Fee income mix", "Capital adequacy"],
        "source": "atlas_midcap_hint",
    },
    "SBIN.NS": {
        "name": "State Bank of India",
        "sector": "Financial Services",
        "subsector": "Public sector bank",
        "pack": "banks",
        "facts": ["Largest public sector bank by deposits."],
        "watch_items": ["Credit cost cycle", "Treasury gains volatility", "Government ownership overlay"],
        "source": "atlas_midcap_hint",
    },
    "INFY.NS": {
        "name": "Infosys",
        "sector": "Information Technology",
        "subsector": "IT services",
        "pack": "saas_it",
        "facts": ["Large-cap Indian IT services exporter."],
        "watch_items": ["Large deal TCV", "Utilization / attrition", "Vertical demand (BFSI, retail)"],
        "source": "atlas_midcap_hint",
    },
    "TCS.NS": {
        "name": "Tata Consultancy Services",
        "sector": "Information Technology",
        "subsector": "IT services",
        "pack": "saas_it",
        "facts": ["Largest Indian IT services company by revenue."],
        "watch_items": ["Deal pipeline", "Margin bridge", "Client concentration"],
        "source": "atlas_midcap_hint",
    },
    "BEL.NS": {
        "name": "Bharat Electronics",
        "sector": "Capital Goods",
        "subsector": "Defence electronics",
        "pack": "defence",
        "facts": ["Defence electronics manufacturer with government program exposure."],
        "watch_items": ["Order book", "Execution delays", "Working capital", "Program concentration"],
        "source": "atlas_midcap_hint",
    },
}


def _pack(
    *,
    id: str,
    label: str,
    thesis_interest: str,
    primary_kpis: list[str],
    extra_questions: list[str],
    risk_lenses: list[str],
    failure_modes: list[str],
    valuation_methods: list[str],
    moat_lenses: list[str],
    management_behaviors: list[str],
    falsifiers: list[str],
    evidence_sources: list[str],
    positive_drivers: list[str],
    concern_drivers: list[str],
    unknown_drivers: list[str],
    bull_seed: str,
    base_seed: str,
    bear_seed: str,
    catalysts: list[str],
    distinctiveness_tokens: list[str],
) -> dict[str, Any]:
    return {
        "id": id,
        "label": label,
        "thesis_interest": thesis_interest,
        "primary_kpis": primary_kpis,
        "extra_questions": extra_questions,
        "risk_lenses": risk_lenses,
        "failure_modes": failure_modes,
        "valuation_methods": valuation_methods,
        "moat_lenses": moat_lenses,
        "management_behaviors": management_behaviors,
        "falsifiers": falsifiers,
        "evidence_sources": evidence_sources,
        "positive_drivers": positive_drivers,
        "concern_drivers": concern_drivers,
        "unknown_drivers": unknown_drivers,
        "bull_seed": bull_seed,
        "base_seed": base_seed,
        "bear_seed": bear_seed,
        "catalysts": catalysts,
        "distinctiveness_tokens": distinctiveness_tokens,
    }


PACKS: dict[str, dict[str, Any]] = {
    "defence": _pack(
        id="defence",
        label="Defence / aerospace manufacturing",
        thesis_interest=(
            "long-cycle defence and aerospace demand for high-precision manufacturing "
            "where order book, program stickiness, and execution quality matter more than "
            "near-term multiples"
        ),
        primary_kpis=[
            "Order book / book-to-bill",
            "Customer concentration (incl. ISRO / defence OEMs)",
            "Receivables days",
            "Working capital / cash conversion",
            "Program execution & certification milestones",
            "Defence / aerospace mix of revenue",
        ],
        extra_questions=[
            "How concentrated is the order book across ISRO, defence OEMs, and export customers?",
            "Are receivables and inventory stretching as programs scale?",
            "Does execution / certification risk delay revenue recognition?",
            "Is defence spending / program continuity the real demand driver — or a single customer?",
            "Does capex create multi-program capacity or chase one contract?",
        ],
        risk_lenses=[
            "Customer / program concentration",
            "ISRO or defence program delay",
            "Receivables / working-capital squeeze",
            "Execution / certification failure",
            "Commodity / specialty input costs",
        ],
        failure_modes=[
            "Single-program dependence that rolls off without replacement",
            "Working-capital blowout that destroys FCF despite revenue growth",
            "Quality / delivery miss that loses preferred-supplier status",
        ],
        valuation_methods=[
            "Order-book-aware earnings / PE (with WC haircut)",
            "FCF yield after normalising receivables",
            "Peer multiples vs defence/precision peers (not generic industrials)",
        ],
        moat_lenses=[
            "Qualification / certification barriers",
            "Process know-how on precision parts",
            "Sticky multi-year program relationships",
        ],
        management_behaviors=[
            "Capex discipline vs order visibility",
            "Customer diversification progress",
            "Honest disclosure on program delays and WC",
        ],
        falsifiers=[
            "Order book collapses or becomes one-customer dominated",
            "Receivables / WC permanently impair cash conversion",
            "Material execution miss on a flagship defence/aerospace program",
            "Loss of key OEM / agency qualification",
        ],
        evidence_sources=[
            "Annual report — order book & customer mix",
            "Quarterly — receivables / inventory notes",
            "Defence / aerospace contract disclosures",
            "Management commentary on program milestones",
        ],
        positive_drivers=[
            "Defence / aerospace demand",
            "High-precision manufacturing capability",
            "Qualification barriers",
        ],
        concern_drivers=[
            "Customer concentration",
            "Working capital / receivables",
            "Execution & program delay risk",
        ],
        unknown_drivers=[
            "Sustainable free cash flow through the cycle",
            "True economic moat beyond current programs",
        ],
        bull_seed=(
            "If diversified order book, controlled receivables, and credible FCF accompany "
            "attractive MoS, revisit size — thesis is execution + demand, not a cheap multiple alone."
        ),
        base_seed=(
            "Research posture: track order book quality, customer concentration, and cash conversion. "
            "Do not size on defence narrative alone — working capital and execution are the usual killers."
        ),
        bear_seed=(
            "If concentration rises, receivables blow out, or a flagship program slips, avoid — "
            "even if the stock looks optically cheap."
        ),
        catalysts=[
            "Order book / customer-mix disclosure",
            "Receivables and WC bridge evidence",
            "Program milestone / certification update",
        ],
        distinctiveness_tokens=[
            "order book",
            "defence",
            "aerospace",
            "isro",
            "receivables",
            "precision",
            "program",
            "working capital",
            "customer concentration",
        ],
    ),
    "healthcare": _pack(
        id="healthcare",
        label="Hospitals / healthcare services",
        thesis_interest=(
            "structural healthcare demand served through a branded hospital network where "
            "occupancy, ARPOB, doctor retention, and bed-expansion ROIC determine compounding"
        ),
        primary_kpis=[
            "Hospital occupancy",
            "ARPOB (avg revenue per occupied bed)",
            "Doctor retention / utilization",
            "Bed expansion & ROIC on new capacity",
            "Payer mix / insurance reimbursement",
            "Same-store growth vs new-bed ramp",
        ],
        extra_questions=[
            "Is occupancy durable across the network, or concentrated in a few flagship hospitals?",
            "What drives ARPOB — case mix, pricing power, or length of stay?",
            "Are doctor retention and clinical capacity keeping up with bed expansion?",
            "Does insurance / reimbursement mix support margins as volumes grow?",
            "Is new-bed ROIC attractive after ramp costs and medical inflation?",
        ],
        risk_lenses=[
            "Healthcare reimbursement / payer mix shift",
            "Doctor attrition or utilization miss",
            "Medical inflation vs pricing power",
            "Occupancy miss on new capacity",
            "Regulatory / clinical quality events",
            "Competition in key clusters",
        ],
        failure_modes=[
            "Expansion that dilutes ROIC for years",
            "Payer squeeze that cuts ARPOB without volume offset",
            "Key doctor / specialty attrition in a cluster",
        ],
        valuation_methods=[
            "EV/EBITDA vs hospital peers (occupancy-normalised)",
            "ROIC on incremental beds vs WACC",
            "FCF after maintenance + growth capex for network",
        ],
        moat_lenses=[
            "Brand / referral network",
            "Cluster density / network effects",
            "Clinical specialty depth",
        ],
        management_behaviors=[
            "Capital allocation between expansion vs existing-hospital ROI",
            "Honesty on occupancy and ARPOB trends",
            "Payer-mix and case-mix disclosure quality",
        ],
        falsifiers=[
            "Sustained occupancy or ARPOB decline",
            "Expansion ROIC clearly below cost of capital",
            "Material doctor attrition in core specialties",
            "Adverse reimbursement / regulatory shock",
        ],
        evidence_sources=[
            "Annual / quarterly — occupancy, ARPOB, beds",
            "Payer mix disclosures",
            "Capex / new hospital ROIC commentary",
            "Clinical quality / regulatory filings",
        ],
        positive_drivers=[
            "Healthcare demand",
            "Brand / network effects",
            "Pricing / case-mix leverage (ARPOB)",
        ],
        concern_drivers=[
            "Expansion execution",
            "Valuation vs growth",
            "Reimbursement / medical inflation",
        ],
        unknown_drivers=[
            "Capital allocation quality across the bed pipeline",
            "Sustainable FCF after growth capex",
        ],
        bull_seed=(
            "If occupancy and ARPOB hold while expansion ROIC stays attractive and MoS appears, "
            "revisit size — thesis is operating leverage on healthcare demand, not a hospital PE screen."
        ),
        base_seed=(
            "Research posture: occupancy, ARPOB, doctor retention, and bed-expansion ROIC. "
            "Do not size on brand narrative alone — reimbursement and expansion execution usually decide outcomes."
        ),
        bear_seed=(
            "If occupancy slips, ARPOB compresses under payer pressure, or new beds destroy ROIC, avoid — "
            "even if the franchise looks high-quality on paper."
        ),
        catalysts=[
            "Occupancy / ARPOB disclosure",
            "Bed expansion ROIC update",
            "Payer / insurance mix evidence",
        ],
        distinctiveness_tokens=[
            "occupancy",
            "arpob",
            "hospital",
            "doctor",
            "bed",
            "reimbursement",
            "healthcare",
            "payer",
            "insurance",
            "case mix",
        ],
    ),
    "manufacturing": _pack(
        id="manufacturing",
        label="Manufacturing / capital goods / EMS",
        thesis_interest=(
            "industrial / EMS manufacturing demand where customer concentration, "
            "gross-margin durability, and working-capital control decide cash returns"
        ),
        primary_kpis=[
            "Customer concentration",
            "Gross margin durability",
            "Working capital cycle",
            "Capacity utilization",
            "Capex vs FCF",
        ],
        extra_questions=[
            "Is the order book / customer base diversified enough vs a few large customers?",
            "Does working capital (inventory + receivables) stay under control through the cycle?",
            "Is capex creating durable capacity or just keeping pace with one program/customer?",
            "Are gross margins durable after input-cost and wage inflation?",
        ],
        risk_lenses=[
            "Customer concentration",
            "Program / certification delay",
            "Commodity / input cost pass-through",
            "Working-capital squeeze",
        ],
        failure_modes=[
            "Customer loss that idles specialised capacity",
            "WC blowout that turns growth cash-negative",
            "Margin compression without pricing power",
        ],
        valuation_methods=[
            "PE / EV-EBITDA vs manufacturing peers",
            "FCF yield after normalising WC",
        ],
        moat_lenses=[
            "Process / scale advantages",
            "Customer switching costs on qualified lines",
        ],
        management_behaviors=[
            "Capex discipline vs demand visibility",
            "Customer diversification",
        ],
        falsifiers=[
            "Major customer exit",
            "Persistent FCF gap despite revenue growth",
            "Gross margin structural decline",
        ],
        evidence_sources=[
            "Annual report — customer mix & WC notes",
            "Quarterly margin bridges",
        ],
        positive_drivers=[
            "Manufacturing / EMS demand",
            "Scale / process capability",
        ],
        concern_drivers=[
            "Customer concentration",
            "Working capital",
            "Margin durability",
        ],
        unknown_drivers=[
            "Sustainable free cash flow",
            "True pricing power",
        ],
        bull_seed=(
            "If diversified demand, controlled WC, and attractive MoS arrive with credible "
            "capital-allocation evidence, revisit buy sizing."
        ),
        base_seed=(
            "Research posture: customer mix, margins, and cash conversion. "
            "Biggest open risk is often working capital / execution — not the headline multiple."
        ),
        bear_seed=(
            "If leverage rises, FCF stays opaque, or a key customer exits, avoid — "
            "even if price looks cheap without inputs."
        ),
        catalysts=[
            "Customer / order disclosure",
            "WC and margin bridge evidence",
            "Deeper research mode",
        ],
        distinctiveness_tokens=[
            "customer concentration",
            "working capital",
            "gross margin",
            "ems",
            "capacity",
            "manufacturing",
        ],
    ),
    "saas_it": _pack(
        id="saas_it",
        label="IT / software services",
        thesis_interest=(
            "services / software demand where deal pipeline, utilization, attrition, "
            "and vertical mix determine margin durability"
        ),
        primary_kpis=[
            "Deal TCV / pipeline",
            "Utilization",
            "Attrition",
            "Vertical mix",
            "Margin bridge",
        ],
        extra_questions=[
            "Is revenue growth organic vs acquisition-led?",
            "Are margins durable after wage inflation?",
            "Is demand broad-based or concentrated in one vertical?",
            "How sticky is the top-client revenue?",
        ],
        risk_lenses=["Client concentration", "Attrition", "Deal slippage", "Currency / geo mix"],
        failure_modes=[
            "Wage inflation that permanently compresses margins",
            "Vertical demand shock (e.g. BFSI) without diversification",
        ],
        valuation_methods=["PE vs IT peers", "FCF yield", "Growth-adjusted multiples"],
        moat_lenses=["Client switching costs", "Domain depth", "Delivery scale"],
        management_behaviors=["Wage vs price discipline", "Capital return vs tuck-in M&A"],
        falsifiers=[
            "Structural margin decline",
            "Large-client exit",
            "Persistent deal slippage",
        ],
        evidence_sources=["Quarterly TCV / attrition", "Vertical commentary"],
        positive_drivers=["Digital / IT demand", "Delivery scale"],
        concern_drivers=["Attrition / wage inflation", "Client concentration"],
        unknown_drivers=["Organic growth durability", "FCF after wage cycle"],
        bull_seed=(
            "If pipeline, utilization, and margins hold with attractive MoS, revisit size."
        ),
        base_seed=(
            "Research posture: pipeline quality, attrition, and margin bridge — not headline growth alone."
        ),
        bear_seed=(
            "If margins compress or large clients leave, avoid even on cheap PE screens."
        ),
        catalysts=["Large-deal TCV", "Attrition / utilization print", "Vertical demand update"],
        distinctiveness_tokens=[
            "attrition",
            "utilization",
            "tcv",
            "pipeline",
            "vertical",
            "it services",
            "wage",
        ],
    ),
    "banks": _pack(
        id="banks",
        label="Banks / NBFCs",
        thesis_interest=(
            "liability franchise and credit-cycle sensitivity where NIM, slippages, "
            "and deposit quality dominate long-term returns"
        ),
        primary_kpis=["NIM", "Credit cost / slippages", "CASA / deposit mix", "Capital adequacy", "Loan growth mix"],
        extra_questions=[
            "Are credit costs normalised or still rising?",
            "Is the liability franchise (CASA / deposits) stable?",
            "Is growth coming from riskier segments?",
        ],
        risk_lenses=["Asset quality", "Funding cost", "Regulatory capital", "Concentration"],
        failure_modes=["Credit-cost spike", "Deposit franchise erosion", "Risky segment overgrowth"],
        valuation_methods=["P/B vs RoE", "P/E with normalised credit cost"],
        moat_lenses=["Liability franchise", "Distribution / brand"],
        management_behaviors=["Underwriting discipline", "Capital return vs growth"],
        falsifiers=["Sustained credit-cost spike", "CASA collapse", "Capital adequacy stress"],
        evidence_sources=["Quarterly asset-quality pack", "NIM bridge", "RBI / regulatory notes"],
        positive_drivers=["Liability franchise", "Credit demand"],
        concern_drivers=["Asset quality cycle", "Funding cost"],
        unknown_drivers=["Normalised credit cost through cycle"],
        bull_seed="If asset quality and franchise hold with attractive valuation vs RoE, revisit size.",
        base_seed="Research posture: NIM, credit costs, and deposit quality — not loan-growth headlines.",
        bear_seed="If credit costs spike or the liability franchise weakens, avoid.",
        catalysts=["Credit-cost print", "CASA / NIM update", "Regulatory capital note"],
        distinctiveness_tokens=["nim", "casa", "slippage", "credit cost", "deposit", "asset quality"],
    ),
}


def hint_for(symbol: str) -> dict[str, Any] | None:
    sym = normalize_symbol(symbol)
    row = _SYMBOL_HINTS.get(sym)
    return dict(row) if row else None


def pack_by_id(pack_id: str | None) -> dict[str, Any] | None:
    if not pack_id:
        return None
    pack = PACKS.get(str(pack_id))
    return dict(pack) if pack else None


def pack_for(symbol: str, *, sector: str | None = None) -> dict[str, Any] | None:
    hint = hint_for(symbol)
    pack_id = None
    if hint:
        pack_id = hint.get("pack")
    if not pack_id and sector:
        s = sector.lower()
        if any(x in s for x in ("bank", "financial", "nbfc")):
            pack_id = "banks"
        elif any(x in s for x in ("information technology", "software", "it ")):
            pack_id = "saas_it"
        elif any(
            x in s
            for x in (
                "healthcare",
                "hospital",
                "pharma",
                "pharmaceutical",
                "health care",
            )
        ):
            pack_id = "healthcare"
        elif any(x in s for x in ("defence", "defense", "aerospace")):
            pack_id = "defence"
        elif any(
            x in s
            for x in (
                "capital goods",
                "automobile",
                "manufactur",
                "industrial",
                "engineering",
            )
        ):
            pack_id = "manufacturing"
    if not pack_id:
        return None
    return pack_by_id(str(pack_id))


def enrich_profile_from_hint(symbol: str) -> dict[str, Any]:
    """Minimal profile dict for MVR when config_seed has no entry."""
    hint = hint_for(symbol)
    if not hint:
        return {}
    return {
        "name": hint.get("name") or symbol,
        "sector": hint.get("sector") or "",
        "subsector": hint.get("subsector") or "",
        "knowledge_text": " ".join(hint.get("facts") or []),
        "facts": list(hint.get("facts") or []),
        "watch_items": list(hint.get("watch_items") or []),
        "pack": hint.get("pack"),
        "source": hint.get("source") or "atlas_midcap_hint",
    }


def build_thesis_drivers(
    sector_pack: dict[str, Any] | None,
    *,
    hint: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Positive / concern / unknown drivers — pack-first, never invented numbers."""
    pack = sector_pack if isinstance(sector_pack, dict) else {}
    positive = list(pack.get("positive_drivers") or [])
    concern = list(pack.get("concern_drivers") or [])
    unknown = list(pack.get("unknown_drivers") or [])
    # Hint watch items that are not already covered become unknowns / concerns
    for w in (hint or {}).get("watch_items") or []:
        w_s = str(w).strip()
        if not w_s:
            continue
        low = w_s.lower()
        blob = " ".join(positive + concern).lower()
        if low in blob:
            continue
        if any(k in low for k in ("risk", "delay", "concentration", "receivable", "attrition")):
            if w_s not in concern:
                concern.append(w_s)
        elif w_s not in unknown and w_s not in positive:
            unknown.append(w_s)
    return {
        "positive": positive[:8],
        "concerns": concern[:8],
        "unknowns": unknown[:8],
        "pack_id": pack.get("id"),
        "primary_kpis": list(pack.get("primary_kpis") or [])[:8],
    }


def thesis_fields_from_pack(
    sector_pack: dict[str, Any] | None,
    *,
    name: str,
    sector: str,
    subsector: str = "",
    stance: str,
    mos_bit: str,
    method: str,
    shallow: list[str],
) -> dict[str, Any]:
    """Pack-driven thesis prose — falls back to generic only when pack missing."""
    pack = sector_pack if isinstance(sector_pack, dict) else {}
    interest = str(pack.get("thesis_interest") or "").strip()
    if not interest:
        interest = (
            f"sector positioning in {sector}"
            if sector and sector != "unknown"
            else "an understandable business sketch"
        )
    shallow_txt = ", ".join(shallow) if shallow else "key fundamentals"
    stance_label = str(stance).replace("_", " ").upper()
    sub = str(subsector or "").strip()
    summary = (
        f"{name} operates in {sector}"
        + (f" ({sub})" if sub else "")
        + f". The business appears interesting because of {interest}. "
        f"However, {shallow_txt} remain insufficiently understood from "
        "hermetic/hint seeds alone. "
        f"Current conclusion: {stance_label} — not BUY. "
        f"({mos_bit}; method={method}.)"
    )
    return {
        "summary": summary,
        "bull": str(pack.get("bull_seed") or (
            "If FCF history and attractive MoS arrive with credible capital-allocation evidence, "
            "revisit buy sizing."
        )),
        "base": str(pack.get("base_seed") or (
            "Hold research posture; do not size on momentum or timing alone."
        )),
        "bear": str(pack.get("bear_seed") or (
            "If leverage rises, FCF stays opaque, or falsifiers hit, avoid."
        )),
        "catalysts": list(pack.get("catalysts") or [
            "Operator filing / screener snapshot",
            "Deeper research mode",
        ])[:6],
        "falsifiers": list(pack.get("falsifiers") or [
            "Persistent FCF gap",
            "Debt stress",
            "Governance / capital-allocation red flags",
            "MoS collapse when valuation becomes measurable",
        ])[:8],
        "interest": interest,
        "valuation_methods_note": list(pack.get("valuation_methods") or [])[:4],
        "moat_lenses": list(pack.get("moat_lenses") or [])[:4],
    }


def thesis_distinctiveness(
    thesis: dict[str, Any] | None,
    sector_pack: dict[str, Any] | None,
    *,
    company_name: str = "",
) -> dict[str, Any]:
    """Could you tell which company this is with the name removed?

    Score rises when pack-specific tokens appear in thesis/drivers/base/falsifiers.
    """
    pack = sector_pack if isinstance(sector_pack, dict) else {}
    thesis = thesis if isinstance(thesis, dict) else {}
    tokens = [str(t).lower() for t in (pack.get("distinctiveness_tokens") or []) if t]
    drivers = thesis.get("drivers") if isinstance(thesis.get("drivers"), dict) else {}
    blob = " ".join(
        str(x)
        for x in (
            thesis.get("summary"),
            thesis.get("base"),
            thesis.get("bull"),
            thesis.get("bear"),
            " ".join(thesis.get("falsifiers") or []),
            " ".join(thesis.get("catalysts") or []),
            " ".join(drivers.get("positive") or []),
            " ".join(drivers.get("concerns") or []),
            " ".join(drivers.get("unknowns") or []),
            " ".join(drivers.get("primary_kpis") or []),
        )
        if x
    ).lower()
    # Strip company name so score reflects business identity, not branding
    name = str(company_name or "").strip().lower()
    if name and len(name) > 3:
        blob = blob.replace(name, " ")
        for part in name.replace(".", " ").split():
            if len(part) > 3:
                blob = blob.replace(part, " ")
    hits = [t for t in tokens if t in blob]
    n = len(tokens) or 1
    score = round(min(1.0, len(hits) / max(3.0, min(n, 6)) * (len(hits) / n) ** 0.5), 3)
    # Simpler readable score 0–100
    pct = round(100.0 * min(1.0, len(hits) / max(4.0, min(n, 8))), 1)
    generic = not pack.get("id") or pct < 35
    return {
        "score_pct": pct,
        "hits": hits[:10],
        "tokens_checked": tokens[:12],
        "pack_id": pack.get("id"),
        "identifiable_without_name": pct >= 50 and bool(pack.get("id")),
        "generic": generic,
        "note": (
            "Thesis distinctiveness: with the company name removed, do pack-specific "
            "KPIs/risks/drivers still identify the business? Low = still a template."
        ),
    }


def sector_kpi_work_items(sector_pack: dict[str, Any] | None, *, limit: int = 4) -> list[dict[str, Any]]:
    """Next-work items from pack primary KPIs (actionable sector lens)."""
    pack = sector_pack if isinstance(sector_pack, dict) else {}
    out: list[dict[str, Any]] = []
    for kpi in list(pack.get("primary_kpis") or [])[: max(1, int(limit))]:
        out.append(
            {
                "kind": "sector_kpi",
                "priority": 1,
                "id": f"kpi:{pack.get('id')}:{kpi[:40]}",
                "text": f"Obtain/verify: {kpi}",
                "reason": f"primary KPI for {pack.get('label') or pack.get('id') or 'sector'} pack",
            }
        )
    return out
