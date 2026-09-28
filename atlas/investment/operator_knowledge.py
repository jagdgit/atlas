"""OI-CU0 A4 — Deterministic Operator Knowledge Pack (market + Atlas-lab glossary).

Small, fixed definitions. No Ollama. Unknown term → None (caller may fall through).
"""

from __future__ import annotations

import re
from typing import Any

VERSION = "cu0.operator_knowledge.v1"

# Canonical term → short operator-facing definition (deterministic).
OPERATOR_GLOSSARY: dict[str, str] = {
    # Market basics
    "f&o": (
        "F&O means Futures & Options — derivative contracts.\n"
        "• A future obligates buy/sell of an underlier at a set price on expiry.\n"
        "• An option gives the right (not obligation) to buy (call) or sell (put).\n"
        "Atlas paper F&O lab studies NIFTY: nearest future for the tape, ATM call "
        "when the underlier is bullish, ATM put when bearish. One lot, no writing, "
        "not live broker orders."
    ),
    "fno": None,  # alias filled below
    "futures and options": None,
    "future": (
        "A futures contract is an agreement to buy or sell an underlier "
        "(e.g. NIFTY) at a fixed price on a future date. Marked to market daily. "
        "Atlas `india_fno_learner` currently studies this via nearest NIFTY FUT "
        "tape plus paper ATM options — not broker execution."
    ),
    "futures": None,
    "option": (
        "An option gives the right, not the obligation, to buy (call) or sell (put) "
        "an underlier at a strike by expiry. Premium is paid upfront. "
        "Atlas F&O lab now papers NIFTY ATM calls and puts from the underlier "
        "SMA (1 lot, no writing) — not a full options book and not live."
    ),
    "options": None,
    "nifty": (
        "NIFTY usually means the Nifty 50 equity index (NSE). "
        "In Atlas F&O lab, 'NIFTY' is the underlier. The book may hold an L4 "
        "index-proxy lot or a paper ATM CE/PE — never a live broker fill."
    ),
    "index": (
        "A market index aggregates many stocks (e.g. Nifty 50) into one level. "
        "It is not a single company. Index-proxy labs track the underlier for learning."
    ),
    "stop loss": (
        "A stop loss is a pre-set exit that sells (or covers) when price hits a "
        "loss threshold. Atlas paper exits today are rule-driven (e.g. SMA/PLC); "
        "this glossary term is educational, not a live broker order type."
    ),
    "p&l": (
        "P&L (profit and loss) is realized or unrealized gain/loss on positions. "
        "Atlas reports day P&L and total P&L per laboratory — simulation only."
    ),
    "pnl": None,
    "e[r]": (
        "E[R] is expected return — Atlas's prototype forecast of return for a "
        "name or cash. Completeness < 1.0 means evidence is incomplete; missing "
        "E[R] is a first-class unknown, not a silent HOLD excuse to invent numbers."
    ),
    "expected return": None,
    "market cap": (
        "Market capitalization ≈ share price × shares outstanding — size of the "
        "equity. Not the same as enterprise value. Atlas may lack it on packets; "
        "unknown stays unknown."
    ),
    "market capitalization": None,
    "pe": (
        "PE (price-to-earnings) = price / earnings per share. "
        "Store coverage (e.g. 18/18) is not the same as packet-time PE on every "
        "decision — open books may still miss FCF/MoS even when PE exists."
    ),
    "p/e": None,
    "price to earnings": None,
    "fcf": (
        "FCF (free cash flow) is cash from operations after sustaining capex — "
        "quality of earnings. Atlas often has PE without FCF; FCF holes block "
        "confident valuation / PLC.A for new swing names."
    ),
    "free cash flow": None,
    # Atlas terminology
    "india_equity_learner": (
        "Swing paper laboratory (`india_equity_learner`).\n"
        "Purpose: thesis-gated multi-day equity learning.\n"
        "Policy: PLC.A fail-closed for new names when fundamentals/thesis incomplete.\n"
        "Simulation only — not broker orders."
    ),
    "swing lab": None,
    "swing laboratory": None,
    "india_fno_learner": (
        "F&O paper laboratory (`india_fno_learner`).\n"
        "Purpose: study F&O-style behaviour in isolation.\n"
        "Current instrument: NIFTY index-proxy lot (daily underlier).\n"
        "Hard constraint: must not switch into cash equities "
        "(lab_instrument_rejected).\n"
        "Simulation only — not live futures."
    ),
    "f&o lab": None,
    "fno lab": None,
    "equity_intraday_learner": (
        "Intraday paper laboratory (`equity_intraday_learner`).\n"
        "Purpose: 5m technical Decision Simulation within NSE cash hours.\n"
        "Policy: technical_only may BUY while thesis=WATCH, but must record "
        "contradiction; book must flatten by EOD (no overnight).\n"
        "Simulation only."
    ),
    "intraday lab": None,
    "intraday laboratory": None,
    "index-proxy": (
        "An index-proxy lot is a paper position sized like an index futures "
        "exposure but marked on the daily underlier (e.g. NIFTY). "
        "It is an L4 laboratory instrument — not a live exchange future."
    ),
    "index proxy": None,
    "next ₹1": (
        "Next ₹1 / next-rupee allocation asks: of holdings + cash + challengers, "
        "where is the best place for the next unit of capital? "
        "ROTATE only when challenger advantage clears threshold + costs; "
        "incomplete E[R] → HOLD is honesty."
    ),
    "next rupee": None,
    "next-rupee": None,
    "challenger": (
        "A challenger is an alternative name (or cash) compared to an incumbent "
        "holding. Atlas builds a daily challenger table with E[R], completeness, "
        "and allocation_action (KEEP/HOLD/ROTATE/CASH)."
    ),
    "switch_block": (
        "switch_blocked means a hold-vs-challenger review did not execute a "
        "rotation — often missing E[R], costs, or advantage below threshold. "
        "Hundreds of raw blocks ≠ hundreds of unique decisions "
        "(many are routine re-marks)."
    ),
    "switch block": None,
    "switch_blocked": None,
    "wso": (
        "WSO (World State Object) is per-symbol working memory: beliefs, "
        "unknowns, falsifiers, revision history. Belief changes should be "
        "evidence-backed or UNREVIEWED — never fake 'unchanged' on LLM failure."
    ),
    "world state object": None,
    "ira": (
        "IRA is Investment Research Agent / research start (hermetic MVR path). "
        "Curiosity may start IRA for data-gap unknowns (FCF, D/E, …). "
        "Research should prioritize unknowns that can change next-₹1 allocation."
    ),
    "learning story": (
        "A learning story is the attributed loop: prediction → allocation → "
        "outcome → error → cause|unknown_explicit → belief update|UNREVIEWED → "
        "next decision change. Required when a qualifying close exists; "
        "never manufactured as a daily vanity metric. "
        "Missing prediction stays prediction_absent."
    ),
    "unknown_explicit": (
        "unknown_explicit means Atlas looked and still has no verified evidence "
        "(e.g. news drain with no headline). It is honesty — better than inventing "
        "PE/FCF/news."
    ),
    "prediction_absent": (
        "prediction_absent means the decision did not state E[R] or direction "
        "before the trade. Atlas must not reconstruct a prediction after the fact."
    ),
    "technical_only": (
        "lab_policy=technical_only (intraday): the technical engine may BUY even "
        "when fundamental thesis is WATCH. That is an experiment — it must record "
        "contradiction and must not rewrite the fundamental thesis from P&L alone."
    ),
    "mos": (
        "MoS (margin of safety) is valuation cushion vs intrinsic estimate. "
        "If PE and MoS are both absent on a packet, Atlas flags mos_unknown — "
        "it does not invent a safety margin."
    ),
    "margin of safety": None,
}

# Resolve aliases to canonical definitions
_ALIAS_TARGETS = {
    "fno": "f&o",
    "futures and options": "f&o",
    "futures": "future",
    "options": "option",
    "pnl": "p&l",
    "expected return": "e[r]",
    "market capitalization": "market cap",
    "p/e": "pe",
    "price to earnings": "pe",
    "free cash flow": "fcf",
    "swing lab": "india_equity_learner",
    "swing laboratory": "india_equity_learner",
    "f&o lab": "india_fno_learner",
    "fno lab": "india_fno_learner",
    "intraday lab": "equity_intraday_learner",
    "intraday laboratory": "equity_intraday_learner",
    "index proxy": "index-proxy",
    "next rupee": "next ₹1",
    "next-rupee": "next ₹1",
    "switch block": "switch_block",
    "switch_blocked": "switch_block",
    "world state object": "wso",
    "margin of safety": "mos",
}
for _alias, _target in _ALIAS_TARGETS.items():
    OPERATOR_GLOSSARY[_alias] = OPERATOR_GLOSSARY[_target]

_WHAT_IS_RE = re.compile(
    r"^\s*(?:(?:can|could|would|will)\s+you\s+)?"
    r"(?:please\s+)?(?:help\s+me\s+)?"
    r"(?:what(?:'s|\s+is|\s+are)|define|explain(?:\s+me)?|"
    r"meaning of|tell me about)\s+(.+?)(?:\?|$)",
    re.IGNORECASE,
)


def normalize_glossary_term(raw: str) -> str:
    t = str(raw or "").strip().lower()
    t = t.strip("?.!\"' ")
    t = re.sub(r"\s+", " ", t)
    # common speech → keys
    t = t.replace("f and o", "f&o").replace("f & o", "f&o")
    t = t.replace("futures and options", "f&o")
    if t in {"fn o", "f n o"}:
        t = "f&o"
    return t


def lookup_glossary(term: str) -> dict[str, Any] | None:
    key = normalize_glossary_term(term)
    if not key:
        return None
    text = OPERATOR_GLOSSARY.get(key)
    if not text:
        # prefix / contained key (longest first)
        for cand in sorted(OPERATOR_GLOSSARY.keys(), key=len, reverse=True):
            if cand and cand in key and OPERATOR_GLOSSARY.get(cand):
                text = OPERATOR_GLOSSARY[cand]
                key = cand
                break
    if not text:
        return None
    return {
        "version": VERSION,
        "term": key,
        "definition": text,
        "deterministic": True,
        "honesty": "Fixed operator glossary — not model-generated; not live edge.",
    }


def match_operator_knowledge(message: str) -> dict[str, Any] | None:
    """Return glossary hit if message is a definitional operator question."""
    text = (message or "").strip()
    if not text:
        return None
    m = _WHAT_IS_RE.match(text)
    candidate = m.group(1).strip() if m else text
    # strip leading articles / filler ("me what is …" already handled by explain me)
    candidate = re.sub(r"^(?:an?\s+|the\s+)", "", candidate, flags=re.IGNORECASE)
    # "f & o in the stock market" → try full phrase then leading token cluster
    hit = lookup_glossary(candidate)
    if hit:
        return hit
    # Prefer known glossary keys appearing anywhere in the ask
    low = normalize_glossary_term(text)
    for cand in sorted(
        (k for k, v in OPERATOR_GLOSSARY.items() if v),
        key=len,
        reverse=True,
    ):
        if len(cand) < 2:
            continue
        # word-ish containment (f&o / fno / pe)
        if cand in low or re.search(
            rf"(?<![a-z0-9]){re.escape(cand)}(?![a-z0-9])", low
        ):
            # Only treat as glossary Q when definitional wrapper present or short ask
            if m or len(text.split()) <= 6 or cand in {
                "f&o",
                "fno",
                "challenger",
                "wso",
                "ira",
            }:
                return lookup_glossary(cand)
    return lookup_glossary(text)


def format_operator_knowledge_answer(
    hit: dict[str, Any],
    *,
    lab_status_line: str | None = None,
) -> str:
    lines = [
        f"Atlas operator knowledge (deterministic — no chat LLM):",
        "",
        f"**{hit.get('term')}**",
        str(hit.get("definition") or "").rstrip(),
    ]
    if lab_status_line:
        lines.extend(["", "Current lab note:", lab_status_line])
    lines.extend(
        [
            "",
            str(hit.get("honesty") or ""),
            "For live books: ask “market intelligence status” or “learner status”.",
        ]
    )
    return "\n".join(lines)


def operator_knowledge_pattern_terms() -> list[str]:
    """Terms safe to put in a planner regex (escaped fragments)."""
    preferred = [
        r"f\s*&\s*o",
        r"fno",
        r"futures?",
        r"options?",
        r"nifty",
        r"index(?:-|\s*)proxy",
        r"stop\s*loss",
        r"p\s*&\s*l",
        r"pnl",
        r"e\[r\]",
        r"expected\s+return",
        r"market\s+cap(?:italization)?",
        r"p/?e",
        r"price\s+to\s+earnings",
        r"fcf",
        r"free\s+cash\s+flow",
        r"india_equity_learner",
        r"india_fno_learner",
        r"equity_intraday_learner",
        r"swing\s+lab(?:oratory)?",
        r"intraday\s+lab(?:oratory)?",
        r"f\s*&\s*o\s+lab",
        r"fno\s+lab",
        r"next\s*(?:₹\s*1|rupee|₹1)",
        r"challenger",
        r"switch[_\s-]?block(?:ed)?",
        r"wso",
        r"world\s+state\s+object",
        r"ira",
        r"learning\s+story",
        r"unknown_explicit",
        r"prediction_absent",
        r"technical_only",
        r"mos",
        r"margin\s+of\s+safety",
        r"index\b",
    ]
    return preferred
