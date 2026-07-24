# Knowledge Verification Plan (KE.4 / V5)

> **Status:** KV.0–KV.10 ✅ · **Date:** 2026-07-24  
> **Trigger:** Media learning emits typed UNVERIFIED findings (V4). Missions need
> knowledge that becomes *trustworthy* — Layer 2 Learning Governance.  
> **Parents:** [`MEDIA_KNOWLEDGE_EXTRACTION_PLAN.md`](MEDIA_KNOWLEDGE_EXTRACTION_PLAN.md)
> (includes live Learning Report review) · [`ATLAS_MISSION_PHILOSOPHY.md`](ATLAS_MISSION_PHILOSOPHY.md) ·
> Verification Engine (Sprint 15)

---

## Alignment with live Learning Report review

The 2026-07-24 COMPLETE media report confirmed:

- Extract + report are **operator-grade** (preview, quality, UNVERIFIED honesty).  
- **Linker is broken in practice** (`claims_linked=0`) — fix in KE.2.4 *before* spending verify budget.  
- Relationships need SPO quality; entities need typing — also KE.2.4 / normalize.  
- Claims-vs-facts distinction is working — do not weaken it in verification.

**Gate:** KE.2.4 claim linking ✅ (`claims_linked` > 0 on investing fixture). KV.1 may proceed; keep Normalize (KV.0.5) in front of verify work.

---

## Why now

Learning (Layer 1): *Can Atlas learn?*  
Verification (Layer 2): *Did Atlas learn something I can trust?*

```
Extract → Normalize → Link → Verify → Consolidate → Mission Consumption
```

Normalize is **in front of** Verify (see KV8).

---

## Frozen decisions

| # | Decision |
|---|----------|
| **KV1** | **Reuse** existing VerificationEngine + EvidenceGraph + Research gather→verify — **no second verifier** |
| **KV2** | Everything enters verification as **UNVERIFIED** |
| **KV3** | Trusted only after corroboration (never at extract — Q5) |
| **KV4** | Start with **single-claim** verify — not distributed graph verifier |
| **KV5** | Learning Reports stay learning; verification is explicit |
| **KV6** | Missions **read** verified knowledge; no parallel truth store |
| **KV7** | Operator Job first; continuous Verification Mission later |
| **KV8** | **Normalize before verify** — aliases (Kiosaki→Kiyosaki), entity types, SPO cleanup |
| **KV9** | Cross-source contradiction **enabled** after single-claim verify stabilized (KV.8) |
| **KV10** | Confidence is **multi-dimensional** — extraction / verification / source reliability / overall (labeled; not one opaque number) |

### Explicit non-goals (now)

- Replacing Research verification  
- Auto-promoting every media claim without evidence  
- Separate graph DB  
- Screener / live market prices as “verification”  

---

## Architecture (reuse)

```
Media / Repo / Archive extract
        │
        ▼
Normalize (KV8)     aliases · entity types · SPO shorten
        │
        ▼
Link (KE.2.4)       claim → concepts / entities / speaker
        │
        ▼
knowledge.findings  (UNVERIFIED + provenance + links)
        │
        ▼
Verification Queue
        │
        ▼
Optional ResearchService gather (budget-capped)
        │
        ▼
Cross-source contradiction (KV.8) → attach contradict evidence
        │
        ▼
EvidenceGraph ← finding + sources
        │
        ▼
VerificationEngine.verify_claim / decide(budget)
        │
        ▼
Write-back confidence / maturity / contested
        │
        ▼
Missions consume higher-trust knowledge (KV6)
```

**Code to wire (do not rewrite):**

| Piece | Path |
|-------|------|
| Engine | `atlas/verification/engine.py` |
| Service | `atlas/verification/service.py` |
| Normalize (KV.0.5) | `atlas/knowledge/normalize.py` |
| Finding→Claim (KV.1) | `atlas/verification/adapt.py` |
| Queue / batch (KV.2–6) | `atlas/verification/queue.py` |
| Gather onto claim (KV.4) | `ResearchService.gather_evidence` in `atlas/research/service.py` |
| Continuous mission (KV.7) | `atlas/workers/knowledge_verification.py` + template `knowledge_verification` |
| Contradiction (KV.8) | `atlas/verification/contradiction.py` |
| Multi-dim trust (KV.10) | `atlas/verification/trust.py` → `quality.trust` |
| Evidence models | `atlas/evidence/models.py` |
| Research loop | `atlas/research/service.py` |
| API | `POST /v1/verify` |
| Tool | `knowledge.verify` |
| Media extract / link | `atlas/knowledge/media_extraction.py` |
| Consolidator | `atlas/knowledge/consolidation.py` |

---

## Multi-dimensional trust (KV10) ✅

Stored on each finding as ``quality.trust`` (labeled dimensions — never one opaque number):

| Dimension | Meaning |
|-----------|---------|
| `extraction_confidence` | Heuristic that the span was extracted correctly (**not** truth) |
| `verification_confidence` | VerificationEngine corroboration score (+ `verification_label`) |
| `source_reliability` | Prior from evidence levels / source class |
| `overall_trust` | Documented blend (default 0.50 / 0.30 / 0.20) for mission consumption |

``findings.confidence`` / ``confidence_score`` stay the VerificationEngine values for compatibility.
Missions should prefer ``overall_trust_from_finding(row)`` / ``quality.trust.overall_trust``.

---

## Ship order

```
KV.0    Plan + open items                         ✅
KE.2.4  Claim link + SPO + entity typing          ✅ gate cleared
KV.0.5  Normalize seam (aliases / types)          ✅
KV.1    Finding → Evidence Claim adapter          ✅
KV.2    Verification queue                        ✅ (finding_reviews + verify_finding)
KV.3    Single-claim verify vs existing Knowledge ✅
KV.4    Optional Research gather (budget-capped)  ✅ (`gather_evidence` + `gather=true`)
KV.5    Write-back confidence/maturity            ✅
KV.6    Operator Job: verify video X claims       ✅ (knowledge.verify + planner)
KV.7    Continuous Verification Mission           ✅ (`knowledge_verification` worker)
KV.8    Cross-source contradiction                ✅ (polarity / SPO / numeric → contested)
KV.10   Multi-dimensional trust                   ✅ (`quality.trust`)
```

---

## Operator-facing success (KV.6)

> Verify claims learned from https://youtu.be/…

- Before/after confidence per claim  
- Supporting / contradicting sources  
- Still-UNVERIFIED vs promoted  
- Explicit that **verification ran**

---

## Relationship to Missions

| Mission | Role of verification |
|---------|----------------------|
| Paper trading | Prefer verified claims in decision context when present |
| Research | Align with same engine |
| Owner / repo | Same queue over time |
| Daily Learning Governance (OI-MP3) | Counts: verified vs still UNVERIFIED |

---

## Checklist

- [x] KV.0 Plan locked (+ review alignment, normalize, multi-dim later, postpone contradiction)  
- [x] KE.2.4 gate (claims_linked > 0)  
- [x] KV.0.5 Normalize seam (`atlas/knowledge/normalize.py`)  
- [x] KV.1 Finding→Claim adapter (`atlas/verification/adapt.py`)  
- [x] KV.2–KV.3 / KV.5 Queue + single-claim verify + write-back (`atlas/verification/queue.py`)  
- [x] KV.6 Operator path (`knowledge.verify` tool + `verify_knowledge` intent)  
- [x] KV.4 Optional Research gather (`ResearchService.gather_evidence`, `gather=true`)  
- [x] KV.7 Continuous Verification Mission (`knowledge_verification` template + worker)  
- [x] KV.8 Cross-source contradiction (`atlas/verification/contradiction.py`)  
- [x] KV.10 Multi-dimensional trust (`atlas/verification/trust.py`)  
- [x] OPEN_ITEMS `OI-KV0`  
- [x] Hermetic tests (`tests/test_knowledge_verification.py`, gather, watcher, contradiction, trust)  

---

## Open discussion — resolved

### Q1 — Auto-verify after every media.learn?
**No for v1.** Queue + operator/Job (KV7 later).

### Q2 — Single YouTube claim → HIGH alone?
**No.** Needs independent sources (Evidence Levels).

### Q3 — Screener / live markets = verification?
**No.** Observation inputs (`OI-D1`); verification corroborates claims.

### Q4 — Normalize before verify?
**Yes (KV8).** Aliases and types before burning search budget.

### Q5 — Multi-dimensional confidence now?
**Yes (KV.10).** Labeled dimensions on ``quality.trust``; ``confidence_score`` remains VerificationEngine-only.

### Q6 — Cross-source contradiction now?
**Yes (KV.8 shipped).** Conservative rules: shared concept/entity (or solid overlap) + polarity/SPO antonym / quantitative divergence. Marks findings ``contested``; VerificationEngine erodes confidence. Toggle with ``detect_contradictions``.
