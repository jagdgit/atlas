"""NOW #5 — ReasoningService Cognitive Core (scientist on evidence packets).

LLM reasons over a bounded evidence packet and returns structured advice.
Deterministic Atlas admits/rejects; never places orders.

On LLM failure → review_status=UNREVIEWED (not silent "unchanged success").

Contract (COG-1): one Core, two typed surfaces — see ``cognitive_contract``.
Core interprets; L2 influences; Auditor validates. Core does not write lessons.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from atlas.llm.provider import ChatMessage
from atlas.reasoning.cognitive_contract import (
    CONTRACT_VERSION,
    CognitiveSurface,
    make_cognitive_result,
    polarity_inverted_vs_expected_effect,
)

VERSION = "now.cognitive_core.v1"
REVIEWED = "REVIEWED"
UNREVIEWED = "UNREVIEWED"
DETERMINISTIC = "DETERMINISTIC"

_log = logging.getLogger("atlas.reasoning.cognitive_core")

_SYSTEM = (
    "You are Atlas's Cognitive Core scientist (advice-only). "
    "Reason only from the evidence packet. Never invent PE/FCF/prices/news. "
    "Unknown stays unknown. Never place orders or recommend sizes. "
    "Respond with ONE JSON object only. First character must be '{'. "
    "No markdown, no preamble, no chain-of-thought."
)


def build_evidence_packet(
    *,
    question: str,
    laboratory_id: str | None = None,
    decision_id: str | None = None,
    symbol: str | None = None,
    action: str | None = None,
    evidence: list[Any] | None = None,
    known: list[Any] | None = None,
    unknowns: list[Any] | None = None,
    prior_belief: dict[str, Any] | list[Any] | None = None,
    contradictions: list[Any] | None = None,
    analogues: list[Any] | None = None,
    experiences: list[Any] | None = None,
    wso_status: str | None = None,
    temporal_note: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Bounded scientist input — citeable facts only; no invented fundamentals."""
    evid = [_clip(x, 240) for x in (evidence or []) if x][:40]
    known_l = [_clip(x, 200) for x in (known or []) if x][:20]
    unk = [_clip(x, 160) for x in (unknowns or []) if x][:20]
    contr = [_clip(x, 200) for x in (contradictions or []) if x][:8]
    anal = [_clip(x, 160) for x in (analogues or []) if x][:6]
    exps: list[dict[str, Any]] = []
    for e in experiences or []:
        if isinstance(e, dict):
            row: dict[str, Any] = {
                "id": e.get("id") or e.get("experience_id"),
                "lesson": _clip(e.get("lesson") or e.get("title") or e.get("statement") or "", 160),
            }
            if e.get("sign") is not None:
                row["sign"] = e.get("sign")
            if isinstance(e.get("expected_effect"), dict):
                row["expected_effect"] = {
                    str(k)[:32]: e["expected_effect"].get(k)
                    for k in ("target", "direction", "confidence")
                    if e["expected_effect"].get(k) is not None
                }
            exps.append(row)
        elif e:
            exps.append({"id": str(e), "lesson": ""})
    prior: Any
    if isinstance(prior_belief, dict):
        prior = {
            k: prior_belief.get(k)
            for k in ("id", "claim", "confidence", "status", "domain", "theme")
            if prior_belief.get(k) is not None
        }
    elif isinstance(prior_belief, list):
        prior = prior_belief[:6]
    else:
        prior = None
    packet: dict[str, Any] = {
        "version": VERSION,
        "contract_version": CONTRACT_VERSION,
        "kind": "EVIDENCE_PACKET",
        "laboratory_id": laboratory_id,
        "decision_id": decision_id,
        "symbol": symbol,
        "action": action,
        "question": (question or "").strip()[:400]
        or "What should Atlas believe / recommend (advice-only) given this evidence?",
        "evidence": evid,
        "known": known_l,
        "unknowns": unk,
        "prior_belief": prior,
        "contradictions": contr,
        "analogues": anal,
        "experiences": exps[:8],
        "wso_status": wso_status,
        "temporal_note": temporal_note
        or (
            "Use only cited evidence. Missing published_at / fundamentals "
            "stay unknown_explicit — never invent PE/FCF/news."
        ),
        "honesty": (
            "Scientist packet — advice-only. Deterministic gates own allocation."
        ),
    }
    if isinstance(extra, dict) and extra:
        packet["extra"] = _sanitize_extra(extra)
    return packet


def _sanitize_extra(extra: dict[str, Any]) -> dict[str, Any]:
    """Keep lesson_refs / no_match typed — do not stringify lists via _clip."""
    out: dict[str, Any] = {}
    for k, v in list(extra.items())[:16]:
        key = str(k)[:64]
        if key in {"lesson_refs", "experience_refs", "tags"} and isinstance(v, list):
            out[key] = [str(x)[:120] for x in v if x][:12]
        elif key == "no_match":
            if isinstance(v, bool):
                out[key] = v
            elif v is None:
                out[key] = None
            else:
                out[key] = str(v).strip().lower() in {"1", "true", "yes"}
        elif isinstance(v, (bool, int, float)) or v is None:
            out[key] = v
        elif isinstance(v, dict):
            out[key] = {str(dk)[:32]: _clip(dv, 80) for dk, dv in list(v.items())[:8]}
        else:
            out[key] = _clip(v, 200)
    return out


def evidence_packet_from_icr_notes(
    notes: dict[str, Any] | None,
    *,
    acp_snapshot: dict[str, Any] | None = None,
    laboratory_id: str | None = None,
) -> dict[str, Any]:
    """Map ICR.5 draft notes + ACP snapshot into a Cognitive Core packet."""
    notes = notes if isinstance(notes, dict) else {}
    snap = acp_snapshot if isinstance(acp_snapshot, dict) else {}
    sym = str(notes.get("symbol") or snap.get("symbol") or "?")
    decision = str(notes.get("acp_decision") or snap.get("decision") or "")
    evidence = [
        f"acp_decision={decision}",
        f"reason_code={snap.get('reason_code') or ''}",
        f"thesis_stance={snap.get('thesis_stance') or ''}",
        f"identity={snap.get('identity') or ''}",
        f"mos_pct={snap.get('mos_pct')}",
        f"best_challenger={snap.get('best_challenger')}",
        f"exit={snap.get('exit_resolution') or notes.get('exit_action')}",
        f"operator_line={snap.get('operator_line') or ''}",
    ]
    known = [
        f"edge={notes.get('incumbent_edge_robust') or ''}",
        *(str(h) for h in (notes.get("flip_hints") or [])[:4]),
    ]
    return build_evidence_packet(
        question=(
            f"For {sym} under ACP={decision}: name contradictions, "
            "unknowns that would flip ranking, edge robustness, and an "
            "advice-only recommendation (no orders)."
        ),
        laboratory_id=laboratory_id,
        symbol=sym,
        action=decision or None,
        evidence=[e for e in evidence if e and not e.endswith("=")],
        known=[k for k in known if k and not k.endswith("=")],
        unknowns=list(notes.get("unknowns_that_flip_ranking") or []),
        contradictions=list(notes.get("contradictions") or []),
        extra={"source": "icr5_draft", "draft_summary": notes.get("summary")},
    )


def empty_advice(
    *,
    review_status: str = UNREVIEWED,
    reason: str | None = None,
    packet: dict[str, Any] | None = None,
    raw_snippet: str | None = None,
) -> dict[str, Any]:
    pkt = packet if isinstance(packet, dict) else {}
    payload = {
        "interpretation": None,
        "recommendation": None,
        "summary": None,
        "explanations": [],
        "contradictions": list(pkt.get("contradictions") or [])[:6],
        "unknowns": list(pkt.get("unknowns") or [])[:8],
        "analogues": list(pkt.get("analogues") or [])[:6],
        "falsifiers": [],
        "question": pkt.get("question"),
    }
    out = make_cognitive_result(
        surface=CognitiveSurface.SCIENTIST,
        review_status=review_status,
        skip_reason=reason,
        claims=[],
        confidence=None,
        provenance=[],
        decision_id=pkt.get("decision_id"),
        laboratory_id=pkt.get("laboratory_id"),
        symbol=pkt.get("symbol"),
        payload=payload,
        version=VERSION,
        kind="SCIENTIST_ADVICE",
        llm=False,
        honesty=(
            "Cognitive Core — advice-only. UNREVIEWED means LLM did not "
            "complete; deterministic gates still own capital."
        ),
        question=pkt.get("question"),
        explanations=[],
        contradictions=payload["contradictions"],
        unknowns=payload["unknowns"],
        analogues=payload["analogues"],
        falsifiers=[],
        recommendation=None,
        summary=None,
    )
    if raw_snippet:
        out["raw_snippet"] = str(raw_snippet)[:240]
    return out


def reason_as_scientist(
    *,
    packet: dict[str, Any] | None,
    llm: Any | None = None,
    purpose: str = "cognitive_core_scientist",
) -> dict[str, Any]:
    """Run scientist over evidence packet. Fail → UNREVIEWED, never silent success."""
    pkt = packet if isinstance(packet, dict) else {}
    if not pkt:
        return empty_advice(review_status=UNREVIEWED, reason="empty_packet")

    if llm is None:
        return empty_advice(
            review_status=UNREVIEWED, reason="no_llm", packet=pkt
        )

    try:
        if hasattr(llm, "lane_busy") and llm.lane_busy():
            return empty_advice(
                review_status=UNREVIEWED, reason="lane_busy", packet=pkt
            )
    except Exception:  # noqa: BLE001
        pass

    prompt = {
        "task": purpose,
        "advice_only": True,
        "never_orders": True,
        "evidence_packet": pkt,
        "return_schema": {
            "summary": "1-2 sentences",
            "recommendation": "str advice-only (no orders/sizes)",
            "unknowns": "list[str]",
            "falsifiers": "list[str]",
            "confidence": "float 0..1 or null",
        },
        "instructions": (
            "Return ONE JSON object only. First char '{'. "
            "No markdown, no preamble, no chain-of-thought. "
            "Do not invent PE/FCF/prices/news. Unknown stays unknown. No order sizes."
        ),
    }
    try:
        client = llm
        if hasattr(llm, "for_role"):
            try:
                client = llm.for_role("scientist")
            except Exception:  # noqa: BLE001
                client = llm.for_role("researcher")
        messages = [
            ChatMessage(role="system", content=_SYSTEM),
            ChatMessage(
                role="user",
                # CPU-bound host: keep packet small so chat finishes inside timeout
                content=json.dumps(prompt, default=str)[:3500],
            ),
        ]
        # Research/scientist needs the long LLM timeout (defaults.yaml llm.timeout),
        # not interactive_chat's shorter wall-clock.
        # CPU/no-GPU: no CoT + bounded decode so JSON advice can complete.
        chat_kw: dict[str, Any] = {
            "_atlas_purpose": purpose,
            "think": False,
            "num_predict": 400,
            "format": "json",
            "temperature": 0.0,
        }
        for src in (client, llm):
            t = getattr(src, "_timeout", None)
            if t is None:
                prov = getattr(src, "_provider", None) or getattr(
                    getattr(src, "_service", None), "_provider", None
                )
                t = getattr(prov, "_timeout", None)
            if t is not None:
                try:
                    chat_kw["timeout"] = float(t)
                    break
                except (TypeError, ValueError):
                    pass
        else:
            chat_kw["timeout"] = 300.0
        resp = client.chat(messages, **chat_kw)
        text = getattr(resp, "text", None) or getattr(resp, "content", None) or ""
        thinking = getattr(resp, "thinking", None) or ""
        # qwen3 often puts the only usable blob in ``thinking`` when think=False
        if not str(text).strip() and thinking:
            text = thinking
        elif thinking and "{" not in str(text) and "{" in str(thinking):
            text = f"{text}\n{thinking}"
    except Exception as exc:  # noqa: BLE001
        name = type(exc).__name__
        reason = "lane_busy" if "LLMLaneBusy" in name or "lane" in str(exc).lower() else f"failed:{name}"
        _log.debug("cognitive_core LLM failed: %s", reason, exc_info=True)
        return empty_advice(review_status=UNREVIEWED, reason=reason, packet=pkt)

    parsed = _parse_json_blob(str(text))
    if not parsed:
        snippet = str(text or "")[:240].replace("\n", " ")
        return empty_advice(
            review_status=UNREVIEWED,
            reason="failed_non_json",
            packet=pkt,
            raw_snippet=snippet,
        )

    conf = parsed.get("confidence")
    try:
        conf_f = float(conf) if conf is not None and conf != "" else None
        if conf_f is not None:
            conf_f = max(0.0, min(1.0, conf_f))
    except (TypeError, ValueError):
        conf_f = None

    # Accept Cognitive Core schema + ICR.5 legacy keys from older prompts
    unknowns = parsed.get("unknowns") or parsed.get("unknowns_that_flip_ranking")
    recommendation = (
        parsed.get("recommendation")
        or parsed.get("incumbent_edge_robust")
        or parsed.get("summary")
    )
    summary = parsed.get("summary") or recommendation
    explanations = _str_list(parsed.get("explanations"), 8, 240)
    falsifiers = _str_list(parsed.get("falsifiers"), 6, 200)
    unknowns_out = _str_list(unknowns or pkt.get("unknowns"), 8, 160)
    contradictions_out = _str_list(
        parsed.get("contradictions") or pkt.get("contradictions"), 6, 200
    )
    analogues_out = _str_list(parsed.get("analogues"), 6, 160)
    payload = {
        "interpretation": _clip(summary, 400) or None,
        "recommendation": _clip(recommendation, 400) or None,
        "summary": _clip(summary, 400) or None,
        "explanations": explanations,
        "contradictions": contradictions_out,
        "unknowns": unknowns_out,
        "analogues": analogues_out,
        "falsifiers": falsifiers,
        "question": pkt.get("question"),
    }
    return make_cognitive_result(
        surface=CognitiveSurface.SCIENTIST,
        review_status=REVIEWED,
        skip_reason=None,
        claims=[],
        confidence=conf_f,
        provenance=[str(x) for x in (pkt.get("evidence") or []) if x][:16],
        decision_id=pkt.get("decision_id"),
        laboratory_id=pkt.get("laboratory_id"),
        symbol=pkt.get("symbol"),
        payload=payload,
        version=VERSION,
        kind="SCIENTIST_ADVICE",
        llm=True,
        honesty=(
            "Cognitive Core REVIEWED — advice-only. Deterministic gates own capital."
        ),
        question=pkt.get("question"),
        explanations=explanations,
        contradictions=contradictions_out,
        unknowns=unknowns_out,
        analogues=analogues_out,
        falsifiers=falsifiers,
        recommendation=payload["recommendation"],
        summary=payload["summary"],
    )


def merge_advice_into_icr_notes(
    notes: dict[str, Any] | None,
    advice: dict[str, Any] | None,
) -> dict[str, Any]:
    """Fold Cognitive Core advice into ICR.5 notes shape (still advice-only)."""
    merged = dict(notes) if isinstance(notes, dict) else {}
    adv = advice if isinstance(advice, dict) else {}
    status = str(adv.get("review_status") or UNREVIEWED)
    merged["cognitive_core"] = {
        "version": VERSION,
        "review_status": status,
        "skip_reason": adv.get("skip_reason"),
        "confidence": adv.get("confidence"),
        "falsifiers": adv.get("falsifiers") or [],
        "analogues": adv.get("analogues") or [],
        "explanations": adv.get("explanations") or [],
        "recommendation": adv.get("recommendation"),
    }
    if adv.get("raw_snippet"):
        merged["cognitive_core"]["raw_snippet"] = str(adv.get("raw_snippet"))[:240]
    merged["review_status"] = status
    if status != REVIEWED:
        # Keep deterministic draft; mark UNREVIEWED explicitly
        merged["llm"] = False
        merged["source"] = merged.get("source") or "deterministic"
        return merged

    if adv.get("contradictions"):
        merged["contradictions"] = list(adv["contradictions"])[:6]
    if adv.get("unknowns"):
        merged["unknowns_that_flip_ranking"] = list(adv["unknowns"])[:8]
    if adv.get("recommendation") or adv.get("summary"):
        edge = adv.get("recommendation") or adv.get("summary")
        if edge:
            merged["incumbent_edge_robust"] = str(edge)[:300]
    if adv.get("summary"):
        merged["summary"] = str(adv["summary"])[:400]
        merged["operator_line"] = merged["summary"][:220]
    merged["source"] = "deterministic+cognitive_core"
    merged["llm"] = True
    merged["advice_only"] = True
    merged["never_orders"] = True
    return merged


def _clip(value: Any, n: int) -> str:
    s = str(value) if value is not None else ""
    return s[:n]


def _str_list(value: Any, limit: int, width: int) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_clip(x, width) for x in value if x][:limit]


def _try_loads_object(s: str) -> dict[str, Any] | None:
    try:
        obj = json.loads(s)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None


def _repair_truncated_object(chunk: str) -> dict[str, Any] | None:
    """Close dangling quotes / brackets so a truncated Qwen blob can still parse."""
    s = (chunk or "").strip()
    if not s or "{" not in s:
        return None
    in_str = False
    escape = False
    braces = 0
    brackets = 0
    for ch in s:
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            braces += 1
        elif ch == "}":
            braces = max(0, braces - 1)
        elif ch == "[":
            brackets += 1
        elif ch == "]":
            brackets = max(0, brackets - 1)
    if in_str:
        s += '"'
    s = s.rstrip()
    if s.endswith(","):
        s = s[:-1]
    s += "]" * brackets
    s += "}" * braces
    return _try_loads_object(s)


def _salvage_decide_json(s: str) -> dict[str, Any] | None:
    """Last resort: pull completed rationale_text / falsifiers from a broken blob."""
    m = re.search(r'"rationale_text"\s*:\s*"((?:\\.|[^"\\])*)"', s or "")
    if not m:
        return None
    try:
        rationale = json.loads(f'"{m.group(1)}"')
    except json.JSONDecodeError:
        rationale = m.group(1)
    out: dict[str, Any] = {"rationale_text": rationale}
    fm = re.search(r'"falsifiers"\s*:\s*(\[(?:[^\[\]]|\[[^\[\]]*\])*\])', s)
    if fm:
        try:
            arr = json.loads(fm.group(1))
            if isinstance(arr, list):
                out["falsifiers"] = arr
        except json.JSONDecodeError:
            pass
    cm = re.search(r'"confidence"\s*:\s*([0-9.]+|null)', s)
    if cm and cm.group(1) != "null":
        try:
            out["confidence"] = float(cm.group(1))
        except ValueError:
            pass
    return out


def _parse_json_blob(text: str) -> dict[str, Any] | None:
    s = (text or "").strip()
    if not s:
        return None
    # Strip reasoning wrappers qwen often emits even with think=False
    if "</think>" in s:
        s = s.split("</think>", 1)[-1].strip()
    if "<think>" in s:
        s = s.split("<think>", 1)[-1]
        if "</think>" in s:
            s = s.split("</think>", 1)[-1].strip()
    # Prefer fenced ```json blocks
    if "```" in s:
        parts = s.split("```")
        for i, part in enumerate(parts):
            chunk = part.strip()
            if chunk.lower().startswith("json"):
                chunk = chunk[4:].strip()
            if chunk.startswith("{"):
                s = chunk
                break
    obj = _try_loads_object(s)
    if obj is not None:
        return obj
    start = s.find("{")
    if start < 0:
        return _salvage_decide_json(s)
    chunk = s[start:]
    obj = _try_loads_object(chunk)
    if obj is not None:
        return obj
    # Brace-balanced extract (handles truncated trailing prose)
    depth = 0
    end = None
    for i, ch in enumerate(s[start:], start=start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
    if end is not None and end > start:
        obj = _try_loads_object(s[start : end + 1])
        if obj is not None:
            return obj
    obj = _repair_truncated_object(chunk)
    if obj is not None:
        return obj
    return _salvage_decide_json(s)


def _clip_unknown(value: Any, n: int = 80) -> str:
    if isinstance(value, dict):
        kind = value.get("conflict_type") or value.get("field") or "dict"
        return _clip(kind, n)
    return _clip(value, n)


def _is_prompt_echo(parsed: dict[str, Any] | None) -> bool:
    """Qwen often copies the user JSON (task/return_schema) instead of the schema."""
    if not isinstance(parsed, dict):
        return False
    if _clip(parsed.get("rationale_text"), 40).strip():
        return False
    keys = set(parsed)
    return bool(keys & {"task", "return_schema", "instructions", "advice_only"})


_SCHEMA_ECHO_TEXT = frozenset(
    {
        "1-3 sentences",
        "str",
        "string",
        "rationale_text",
        "your actual reasoning",
    }
)
_SCHEMA_ECHO_TOKEN = frozenset({"str", "string", "falsifier"})


def _is_schema_echo(parsed: dict[str, Any] | None) -> bool:
    """Qwen copied the example skeleton (rationale_text='1-3 sentences')."""
    if not isinstance(parsed, dict):
        return False
    rat = _clip(parsed.get("rationale_text"), 80).strip().lower()
    if rat in _SCHEMA_ECHO_TEXT:
        return True
    fals = [_clip(x, 40).strip().lower() for x in (parsed.get("falsifiers") or []) if x]
    if fals and all(tok in _SCHEMA_ECHO_TOKEN for tok in fals):
        return True
    claims = [c for c in (parsed.get("claims") or []) if isinstance(c, dict)]
    if claims and all(
        _clip(c.get("text"), 40).strip().lower() in _SCHEMA_ECHO_TOKEN for c in claims
    ):
        return True
    return False


def _render_decide_user_prompt(
    pkt: dict[str, Any],
    *,
    purpose: str,
    allowed: set[str],
) -> str:
    """Plain-text user turn — JSON-in/JSON-out made Qwen echo the prompt (2026-09-23)."""
    extra = pkt.get("extra") if isinstance(pkt.get("extra"), dict) else {}
    no_match = extra.get("no_match")
    lesson_refs: list[str] = []
    if no_match is not True:
        extra_refs = extra.get("lesson_refs")
        if isinstance(extra_refs, list) and extra_refs:
            lesson_refs = [str(x) for x in extra_refs if x][:6]
        else:
            for e in (pkt.get("experiences") or [])[:6]:
                rid = e.get("id") if isinstance(e, dict) else e
                if rid:
                    lesson_refs.append(str(rid))
    unk = [_clip_unknown(u) for u in (pkt.get("unknowns") or [])[:5] if u]
    known = [_clip(k, 80) for k in (pkt.get("known") or [])[:3] if k]
    lines = [
        "Reply with ONLY a JSON object. Do not copy these instructions. First character '{'.",
        "Keys: rationale_text (your reasoning, not a template), falsifiers (what would prove you wrong),",
        "expected_outcome, claims (each: text + evidence_ids from the allowed list), confidence 0-1.",
        f"task={purpose} advice_only=true never_orders=true",
        f"symbol={pkt.get('symbol')} action={pkt.get('action')}",
        f"no_match={no_match}",
        f"unknowns={json.dumps(unk, default=str)}",
        f"known={json.dumps(known, default=str)}",
        f"lesson_refs={json.dumps(lesson_refs)}",
        f"allowed_evidence_ids={json.dumps(sorted(allowed)[:16])}",
        "If no_match, do not invent a lesson. Cite lesson_refs only when they apply.",
        "Unknown stays unknown. Never emit BUY/SELL/qty.",
    ]
    # Negative buy_score lessons carry expected_effect — prompt from that, not ids.
    lesson_effects: list[str] = []
    for e in (pkt.get("experiences") or [])[:6]:
        if not isinstance(e, dict):
            continue
        ee = e.get("expected_effect") if isinstance(e.get("expected_effect"), dict) else None
        if not ee:
            try:
                from atlas.reasoning.cognitive_contract import lesson_expected_effect

                ee = lesson_expected_effect(e)
            except Exception:  # noqa: BLE001
                ee = None
        if not ee or ee.get("direction") in (None, "unknown"):
            continue
        lid = e.get("id") or "?"
        lesson_effects.append(
            f"{lid}: expected_effect target={ee.get('target')} "
            f"direction={ee.get('direction')} — interpret accordingly; "
            "never invert a negative buy_score lesson into buy support."
        )
    if lesson_effects:
        lines.append("Lesson semantic contracts:")
        lines.extend(lesson_effects[:4])
    return "\n".join(lines)[:2200]


def evidence_packet_from_decide(
    doc: dict[str, Any] | None,
    *,
    laboratory_id: str | None = None,
    scientist_packet: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Map BRE.3 decide-rationale sidecar into a Cognitive Core evidence packet."""
    doc = doc if isinstance(doc, dict) else {}
    summary = doc.get("packet_summary") if isinstance(doc.get("packet_summary"), dict) else {}
    sp = scientist_packet if isinstance(scientist_packet, dict) else {}
    sym = str(doc.get("symbol") or summary.get("symbol") or sp.get("symbol") or "?")
    action = str(doc.get("action") or summary.get("action") or sp.get("action") or "")
    evid = list(doc.get("evidence_ids") or sp.get("evidence_ids") or summary.get("evidence_ids") or [])
    reasons = list(summary.get("reasons_for") or summary.get("reasons") or [])
    known = [f"reason:{r}" for r in reasons[:8] if r]
    unk = list(
        doc.get("unknowns")
        or sp.get("unknowns")
        or summary.get("unknowns")
        or []
    )
    lessons = list(summary.get("lesson_refs") or doc.get("lesson_refs") or [])
    exp_refs = list(summary.get("experience_refs") or doc.get("experience_refs") or [])
    experiences: list[dict[str, Any]] = []
    for ref in (lessons + exp_refs)[:8]:
        if isinstance(ref, dict):
            row = dict(ref)
            if "expected_effect" not in row:
                try:
                    from atlas.reasoning.cognitive_contract import lesson_expected_effect

                    row["expected_effect"] = lesson_expected_effect(row)
                except Exception:  # noqa: BLE001
                    pass
            experiences.append(row)
        elif ref:
            rid = str(ref)
            row: dict[str, Any] = {"id": rid, "lesson": rid[:160]}
            try:
                from atlas.investment.lesson_influence import (
                    E001_LESSON_ID,
                    canonical_e001_lesson,
                )

                if rid == E001_LESSON_ID or "E001" in rid:
                    canon = canonical_e001_lesson()
                    row["lesson"] = str(canon.get("statement") or "")[:160]
                    row["sign"] = canon.get("sign")
                    row["expected_effect"] = canon.get("expected_effect")
            except Exception:  # noqa: BLE001
                pass
            experiences.append(row)
    return build_evidence_packet(
        question=(
            f"Write an advice-only decide-time rationale for {action} {sym}. "
            "Cite only allowed evidence_ids and lesson_refs; list falsifiers; "
            "do not invent PE/FCF. Honest no_match means no lesson applied."
        ),
        laboratory_id=laboratory_id or doc.get("laboratory_id") or sp.get("laboratory_id"),
        decision_id=str(doc.get("decision_id") or sp.get("decision_id") or "") or None,
        symbol=sym,
        action=action or None,
        evidence=[str(x) for x in evid if x][:40]
        + [f"reasons_for:{r}" for r in reasons[:6] if r],
        known=known,
        unknowns=[str(u) for u in unk if u][:20],
        experiences=experiences,
        extra={
            "source": "bre3_decide",
            "allowed_evidence_n": len(evid),
            "no_match": summary.get("no_match") if summary.get("no_match") is not None else doc.get("no_match"),
            "lesson_refs": [str(x) for x in lessons if x][:12],
            "lesson_ref_n": len(lessons),
        },
    )


def empty_decide_rationale(
    *,
    review_status: str = UNREVIEWED,
    reason: str | None = None,
    packet: dict[str, Any] | None = None,
    llm: bool = False,
    raw_llm_text: str | None = None,
) -> dict[str, Any]:
    pkt = packet if isinstance(packet, dict) else {}
    payload = {
        "rationale_text": None,
        "falsifiers": [],
        "expected_outcome": None,
        "claims": [],
        "rejected_claims": 0,
        "question": pkt.get("question"),
    }
    out = make_cognitive_result(
        surface=CognitiveSurface.DECIDE_RATIONALE,
        review_status=review_status,
        skip_reason=reason,
        claims=[],
        confidence=None,
        provenance=[],
        decision_id=pkt.get("decision_id"),
        laboratory_id=pkt.get("laboratory_id"),
        symbol=pkt.get("symbol"),
        payload=payload,
        version=VERSION,
        kind="DECIDE_RATIONALE_ADVICE",
        llm=bool(llm),
        honesty=(
            "Decide-time Cognitive Core — advice-only. UNREVIEWED means LLM "
            "did not complete; packet/reasons_for stay frozen."
        ),
        question=pkt.get("question"),
        rationale_text=None,
        falsifiers=[],
        expected_outcome=None,
        rejected_claims=0,
    )
    if raw_llm_text:
        out["raw_llm_text"] = str(raw_llm_text)[:2000]
    return out


def evidence_packet_from_engineering(
    mentor: Any,
    *,
    decision_id: str | None = None,
    laboratory_id: str = "engineering_mentor",
) -> dict[str, Any]:
    """Map an Engineering Mentor lesson / experience into a generic Core packet.

    No market fields required — proves domain-agnostic Cognitive Core (COG-4).
    """
    if hasattr(mentor, "as_dict") and callable(mentor.as_dict):
        doc = mentor.as_dict()
    elif isinstance(mentor, dict):
        doc = mentor
    else:
        doc = {}
    title = str(doc.get("title") or "Engineering judgment")[:200]
    lesson = str(doc.get("lesson") or doc.get("lessons") or "")[:400]
    observation = str(doc.get("observation") or doc.get("problem") or "")[:300]
    reflection = str(doc.get("reflection") or doc.get("solution") or "")[:300]
    recs = doc.get("recommendations") or []
    if isinstance(recs, list):
        rec_s = [
            str(r.get("title") if isinstance(r, dict) else r)[:120] for r in recs if r
        ]
    else:
        rec_s = []
    src_ids = [
        str(x)
        for x in (doc.get("source_experience_ids") or doc.get("experience_ids") or [])
        if x
    ][:12]
    decision = decision_id or str(doc.get("decision_id") or "") or None
    if not decision and src_ids:
        decision = f"eng-{src_ids[0]}"
    evidence = [
        f"title:{title}",
        f"observation:{observation}" if observation else "",
        f"lesson:{lesson}" if lesson else "",
        f"reflection:{reflection}" if reflection else "",
    ]
    evidence = [e for e in evidence if e and not e.endswith(":")]
    evidence.extend([f"recommendation:{r}" for r in rec_s[:6]])
    evidence.extend([f"source_experience:{x}" for x in src_ids[:6]])
    return build_evidence_packet(
        question=(
            f"Engineering advice-only: interpret this mentor judgment for "
            f"future repository decisions. Topic: {title}"
        ),
        laboratory_id=laboratory_id,
        decision_id=decision,
        symbol=None,
        action=None,
        evidence=evidence[:40],
        known=["domain:engineering", f"mentor_topic:{title}"][:8],
        unknowns=["whether_pattern_still_applies"],
        experiences=[
            {
                "id": sid,
                "lesson": lesson[:160] if lesson else title[:160],
            }
            for sid in (src_ids or [decision or "engineering_mentor"])[:4]
        ],
        extra={
            "source": "engineering_mentor",
            "domain": "engineering",
            "tags": list(doc.get("tags") or [])[:8],
        },
    )


def reason_decide_rationale(
    *,
    packet: dict[str, Any] | None,
    llm: Any | None = None,
    allowed_evidence_ids: list[Any] | None = None,
    purpose: str = "bre3_decide_rationale",
    role: str = "market",
) -> dict[str, Any]:
    """Decide-time scientist: rationale + falsifiers on bounded evidence.

    Fail → UNREVIEWED (never silent ``done``).
    """
    pkt = packet if isinstance(packet, dict) else {}
    if not pkt:
        return empty_decide_rationale(review_status=UNREVIEWED, reason="empty_packet")
    if llm is None:
        return empty_decide_rationale(
            review_status=UNREVIEWED, reason="no_llm", packet=pkt
        )

    try:
        if hasattr(llm, "lane_busy") and llm.lane_busy():
            return empty_decide_rationale(
                review_status=UNREVIEWED, reason="lane_busy", packet=pkt
            )
    except Exception:  # noqa: BLE001
        pass

    allowed = {str(x) for x in (allowed_evidence_ids or []) if x}
    user_prompt = _render_decide_user_prompt(pkt, purpose=purpose, allowed=allowed)
    try:
        client = llm
        if hasattr(llm, "for_role"):
            try:
                client = llm.for_role(role)
            except Exception:  # noqa: BLE001
                try:
                    client = llm.for_role("scientist")
                except Exception:  # noqa: BLE001
                    client = llm.for_role("researcher") if hasattr(llm, "for_role") else llm
        messages = [
            ChatMessage(
                role="system",
                content=(
                    "You are Atlas's investment cortex at decide-time (advice-only). "
                    "Output only the rationale JSON object. Never repeat the prompt. "
                    "Never place orders."
                ),
            ),
            ChatMessage(role="user", content=user_prompt),
        ]
        chat_kw: dict[str, Any] = {
            "_atlas_purpose": purpose,
            "think": False,
            "num_predict": 400,
            "format": "json",
            "temperature": 0.0,
        }
        for src in (client, llm):
            t = getattr(src, "_timeout", None)
            if t is None:
                prov = getattr(src, "_provider", None) or getattr(
                    getattr(src, "_service", None), "_provider", None
                )
                t = getattr(prov, "_timeout", None)
            if t is not None:
                try:
                    chat_kw["timeout"] = float(t)
                    break
                except (TypeError, ValueError):
                    pass
        else:
            chat_kw["timeout"] = 300.0
        resp = client.chat(messages, **chat_kw)
        text = getattr(resp, "text", None) or getattr(resp, "content", None) or ""
        thinking = getattr(resp, "thinking", None) or ""
        if not str(text).strip() and thinking:
            text = thinking
        elif thinking and "{" not in str(text) and "{" in str(thinking):
            text = f"{text}\n{thinking}"
    except Exception as exc:  # noqa: BLE001
        name = type(exc).__name__
        reason = (
            "lane_busy"
            if "LLMLaneBusy" in name or "lane" in str(exc).lower()
            else f"failed:{name}"
        )
        _log.debug("decide_rationale LLM failed: %s", reason, exc_info=True)
        return empty_decide_rationale(
            review_status=UNREVIEWED, reason=reason, packet=pkt
        )

    raw_clip = str(text or "")[:2000]
    parsed = _parse_json_blob(str(text))
    if _is_prompt_echo(parsed):
        return empty_decide_rationale(
            review_status=UNREVIEWED,
            reason="failed_prompt_echo",
            packet=pkt,
            llm=True,
            raw_llm_text=raw_clip,
        )
    if _is_schema_echo(parsed):
        return empty_decide_rationale(
            review_status=UNREVIEWED,
            reason="failed_schema_echo",
            packet=pkt,
            llm=True,
            raw_llm_text=raw_clip,
        )
    if not parsed:
        return empty_decide_rationale(
            review_status=UNREVIEWED,
            reason="failed_non_json",
            packet=pkt,
            llm=True,
            raw_llm_text=raw_clip,
        )

    claims_in = list(parsed.get("claims") or [])
    claims_out: list[dict[str, Any]] = []
    rejected = 0
    for c in claims_in:
        if not isinstance(c, dict):
            continue
        cites = [str(x) for x in (c.get("evidence_ids") or c.get("citations") or []) if x]
        if cites and allowed and not any(x in allowed for x in cites):
            rejected += 1
            continue
        claims_out.append(
            {
                "text": _clip(c.get("text"), 240),
                "evidence_ids": cites[:12],
            }
        )

    rationale = _clip(parsed.get("rationale_text"), 1200).strip()
    falsifiers = _str_list(parsed.get("falsifiers"), 8, 200)
    expected = parsed.get("expected_outcome")
    if expected is not None:
        expected = _clip(expected, 300) or None
    conf = parsed.get("confidence")
    try:
        conf_f = float(conf) if conf is not None and conf != "" else None
        if conf_f is not None:
            conf_f = max(0.0, min(1.0, conf_f))
    except (TypeError, ValueError):
        conf_f = None

    if not rationale and not falsifiers:
        return empty_decide_rationale(
            review_status=UNREVIEWED,
            reason="empty_rationale_and_falsifiers",
            packet=pkt,
            llm=True,
            raw_llm_text=raw_clip,
        )

    # Semantic guard: lesson.expected_effect vs LLM text (E001 is the fixture).
    try:
        extra = pkt.get("extra") if isinstance(pkt.get("extra"), dict) else {}
        raw_refs = extra.get("lesson_refs") or []
        if isinstance(raw_refs, str):
            lesson_refs = [raw_refs]
        elif isinstance(raw_refs, list):
            lesson_refs = list(raw_refs)
        else:
            lesson_refs = []
        claim_blob = " ".join(
            str(c.get("text") or "") for c in claims_out if isinstance(c, dict)
        )
        lessons_ctx: list[dict[str, Any]] = []
        for row in pkt.get("experiences") or []:
            if not isinstance(row, dict):
                continue
            enriched = dict(row)
            rid = str(enriched.get("id") or "")
            ee = enriched.get("expected_effect")
            if not isinstance(ee, dict) or not ee.get("direction") or ee.get("direction") == "unknown":
                try:
                    from atlas.investment.lesson_influence import (
                        E001_LESSON_ID,
                        canonical_e001_lesson,
                    )

                    if rid == E001_LESSON_ID or "E001" in rid:
                        enriched = canonical_e001_lesson()
                except Exception:  # noqa: BLE001
                    pass
            lessons_ctx.append(enriched)
        if not lessons_ctx and lesson_refs:
            try:
                from atlas.investment.lesson_influence import (
                    E001_LESSON_ID,
                    canonical_e001_lesson,
                )

                for ref in lesson_refs:
                    rid = str(ref)
                    if rid == E001_LESSON_ID or "E001" in rid:
                        lessons_ctx.append(canonical_e001_lesson())
                    else:
                        lessons_ctx.append({"id": rid})
            except Exception:  # noqa: BLE001
                lessons_ctx = [{"id": str(x)} for x in lesson_refs if x]
        if polarity_inverted_vs_expected_effect(
            f"{rationale} {claim_blob}",
            lessons=lessons_ctx,
            lesson_refs=lesson_refs or [r.get("id") for r in lessons_ctx if r.get("id")],
        ):
            return empty_decide_rationale(
                review_status=UNREVIEWED,
                reason="failed_polarity_inversion",
                packet=pkt,
                llm=True,
                raw_llm_text=raw_clip,
            )
    except Exception:  # noqa: BLE001
        _log.debug("expected_effect polarity guard skipped", exc_info=True)

    payload = {
        "rationale_text": rationale or None,
        "falsifiers": falsifiers,
        "expected_outcome": expected,
        "claims": claims_out[:12],
        "rejected_claims": rejected,
        "question": pkt.get("question"),
    }
    return make_cognitive_result(
        surface=CognitiveSurface.DECIDE_RATIONALE,
        review_status=REVIEWED,
        skip_reason=(f"dropped {rejected} uncited claims" if rejected else None),
        claims=claims_out[:12],
        confidence=conf_f,
        provenance=[
            eid
            for c in claims_out[:12]
            if isinstance(c, dict)
            for eid in (c.get("evidence_ids") or [])
            if eid
        ][:16],
        decision_id=pkt.get("decision_id"),
        laboratory_id=pkt.get("laboratory_id"),
        symbol=pkt.get("symbol"),
        raw_llm_text=raw_clip,
        payload=payload,
        version=VERSION,
        kind="DECIDE_RATIONALE_ADVICE",
        llm=True,
        honesty=(
            "Decide-time Cognitive Core REVIEWED — advice-only. "
            "Deterministic gates own capital."
        ),
        question=pkt.get("question"),
        rationale_text=rationale or None,
        falsifiers=falsifiers,
        expected_outcome=expected,
        rejected_claims=rejected,
    )
