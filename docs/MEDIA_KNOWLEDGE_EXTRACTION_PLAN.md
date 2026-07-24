# Media → Knowledge Extraction (KE*)

> **Status:** KE.0–KE.2.4 ✅ · **Next:** KE.2.5 SPO + structured preview · Verification ✅ (`OI-KV0`) · **Date:** 2026-07-24  
> **Trigger:** First COMPLETE `speech_ingested` run — transcript learning works;
> categories showed concepts/entities/facts = 0 while RAG chunks = 71.  
> **Parent:** [`MEDIA_ASSET_LIFECYCLE_PLAN.md`](MEDIA_ASSET_LIFECYCLE_PLAN.md) ·
> [`ATLAS_PLATFORM_ARCHITECTURE.md`](ATLAS_PLATFORM_ARCHITECTURE.md)  
> **Verification:** [`KNOWLEDGE_VERIFICATION_PLAN.md`](KNOWLEDGE_VERIFICATION_PLAN.md) (KV.0–KV.10 ✅)  
> **Program proving ground:** [`MARKET_INTELLIGENCE_MISSIONS_PLAN.md`](MARKET_INTELLIGENCE_MISSIONS_PLAN.md)

---

## Live Learning Report review (2026-07-24) — first pass

Operator assessment of the post–KE.2.3 COMPLETE report (Kiyosaki investing video).

### Maturity scorecard (first pass)

| Area | Status |
|------|--------|
| Acquisition | ✅ Mature |
| Speech → Transcript | ✅ Mature |
| Typed extraction | ✅ Mature |
| Learning report | ✅ Mature |
| Operator observability | ✅ Much improved (preview + quality) |
| Semantic quality | 🟡 Improved (KE.2.4 link/SPO/typing); still iterative |
| Verification | ✅ KV.0–KV.10 (`OI-KV0`) — **not** part of media.learn job |

---

## Second live review (same video, post–KE.2.4) — 2026-07-24 evening

| Area | Previous | Current | Status |
|------|----------|---------|--------|
| Entity extraction | Good | Better | ✅ |
| Entity typing | Improved | Improved | ✅ (`South Africa` = place) |
| Claim linking | 0/12 | **12/12** | ⭐ |
| Orphan claims | 12 | **0** | ⭐ |
| Relationships | 4 | 5 | 🟡 still fragments |
| Knowledge preview | Added | Better | ✅ |
| Facts | 0 | 0 | ✅ correct (UNVERIFIED claims only) |
| Verification separation | Correct | Correct | ✅ Learning Report ≠ verify |

**Score:** ~7.8/10 → **~8.8/10**.

Claim→Concept→Entity linking is now the foundation for “which concepts support this claim?” at verify/reason time.

### Remaining defects

| Signal | Action |
|--------|--------|
| Relationships still sentence fragments (`what baffles me is that teaches…`) | **KE.2.5** — emit only real SPO triples |
| Preview shows raw relationship text | **KE.2.6** — Subject / Predicate / Object in Learning Report |
| Provenance should be complete even if UI hides it | **KE.2.7** — asset, chunk, speaker, timestamp, extractor version |

### Do not expand claim_types

Diminishing returns. Prioritize quality + graph + Mission Context API ([`ATLAS_PLATFORM_ARCHITECTURE.md`](ATLAS_PLATFORM_ARCHITECTURE.md)).

### Generation map (aligned with platform)

| Gen | Capability |
|-----|------------|
| V4 | Media → Transcript → Knowledge Extraction ✅ |
| V4.1 | Link / typing / normalize ✅ KE.2.4 |
| V4.2 | SPO + structured preview + provenance **KE.2.5–2.7** |
| V5 | Verification ✅ |
| V6 | Knowledge Graph + cross-source merge |
| V6.5 | World Models |
| V7 | Reasoning → Mission Decisions (Context API) |
| V8 | Outcomes → Experience → Better Decisions |

---

## How to verify this video’s claims

Learning jobs **do not** run verification (by design). After COMPLETE:

```text
Verify claims learned from https://youtu.be/zHt5Mdr0QFk
```

Optional gather:

```text
Verify claims learned from https://youtu.be/zHt5Mdr0QFk with web search
```

Or filter by `asset_id` from the Learning Report Observations.  
Expect multi-dim trust on `quality.trust`; single YouTube evidence alone will not become HIGH.

### What worked

- **Knowledge Preview** — Top Concepts/Entities/Claims let operators judge quality in seconds (KE11 validated).
- **Extraction Quality** — `candidates_emitted` / caps / linked / orphan separates *extractor* vs *linker* health (KE13 validated).
- **Claims vs Facts** — `claims=12`, `facts=0` on an interview is the correct epistemic call (KE3).
- Pipeline stages and methodology are internally consistent (UNVERIFIED findings explicit).

### Highest-impact defects observed

| Signal | Diagnosis | Action |
|--------|-----------|--------|
| `claims_linked=0` / `orphan_claims=12` | Linker too weak: only matched already-emitted concept names in claim text; speaker not counted as entity link | **KE.2.4** — lexicon-wide match + speaker→entity link |
| Relationships look like sentence fragments | Regex captures long clauses as subject/object | **KE.2.4** — tighten SPO; prefer lexicon anchors |
| `South Africa (person)`, role titles as person | Proper-name heuristic over-assigns `person` | **KE.2.4** — place/role typing |
| Relationships still few | Conservative predicates OK; quality > quantity | Monitor after SPO fix; do not invent edges |

### Sprint priority (quality before new feature kinds)

1. **Claim linking** — connect claims → concepts/entities (`claims_linked` >> 0)  
2. **Relationship SPO** — `Subject · predicate · Object`, not sentence fragments  
3. **Entity normalization / typing** — places, roles, spelling aliases (feeds KV normalize)  
4. **Verification queue (V5)** — [`KNOWLEDGE_VERIFICATION_PLAN.md`](KNOWLEDGE_VERIFICATION_PLAN.md)

Target end-to-end lifecycle:

```
Observe → Extract → Normalize → Link → Verify → Consolidate
       → Knowledge Graph → Mission Consumption → Experience
```

---

## Generation map (operator view)

| Gen | Capability |
|-----|------------|
| V1 | Download media |
| V2 | Metadata learning |
| V3 | Speech → Transcript |
| **V4** | **Transcript → Structured Knowledge** ✅ |
| V4.1 | Semantic quality (link / SPO / entity) ← KE.2.4 |
| V5 | Verification queue → confidence | 📋 [`KNOWLEDGE_VERIFICATION_PLAN.md`](KNOWLEDGE_VERIFICATION_PLAN.md) |
| V6 | Cross-source graph / long-term memory (future) |

---

## Frozen decisions

| # | Decision |
|---|----------|
| **KE1** | Stop investing in acquisition; next product is Knowledge Extraction after transcript |
| **KE2** | Reuse CandidateConsumer + Consolidator (no parallel KB) |
| **KE3** | Claims ≠ facts (interview → many claims, few facts is correct) |
| **KE4** | `knowledge_produced` = RAG transcript chunks; categories separate |
| **KE5** / **Q5** | No scored truth confidence at extract time |
| **KE11** | Learning Report Knowledge Preview (top N) — **validated live** |
| **KE12** | Claim↔concept/entity links on `value` — **must produce non-zero `claims_linked` in practice** |
| **KE13** | Extraction quality = health metrics (linked vs orphan) — **validated live** |
| **KE14** | Stop expanding claim_types; quality + verification next |
| **KE15** | Relationships must be structured SPO (short subject/object); reject clause fragments |
| **KE16** | Entity typing: person / place / org / work / role — fix obvious mis-types before verify |

---

## Architecture (locked)

```
Transcript
   │
   ▼
Extract (typed candidates, UNVERIFIED)
   │
   ▼
Normalize (aliases, entity types)          ← KE.2.4 + KV.0.5
   │
   ▼
Link (claim → concepts/entities/speaker) ← KE.2.4 must work
   │
   ▼
Consolidator → findings
   │
   ▼
Learning Report (preview + quality)
   │
   └── V5 Verify (separate plan)
```

---

## Ship order

```
KE.0–KE.2.3   Metrics, typed extract, preview, provenance     ✅
KE.2.4        Claim link + SPO tighten + entity typing        ✅
KE.2.5        SPO-only relationships (reject fragments)       ← next
KE.2.6        Structured relationship preview in Learning Report
KE.2.7        Provenance completeness (asset/chunk/speaker/ts/version)
KE.4 / V5     Verification                                    ✅ KNOWLEDGE_VERIFICATION_PLAN
KG.1 / V6     Knowledge graph                                 platform
```

---

## Checklist

- [x] KE.0–KE.2.3  
- [x] Live review captured (first + second pass)  
- [x] KE.2.4 Claim linking (`claims_linked` > 0 on investing transcript)  
- [x] KE.2.4 Relationship SPO quality (partial — still fragments on live report)  
- [x] KE.2.4 Entity place/role typing  
- [x] Tests + OI-KE0 update  
- [ ] KE.2.5 SPO-only emission  
- [ ] KE.2.6 Structured Top Relationships in report  
- [ ] KE.2.7 Provenance completeness audit  
