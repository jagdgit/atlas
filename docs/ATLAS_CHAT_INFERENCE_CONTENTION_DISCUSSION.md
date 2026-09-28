# Atlas Chat × Ollama — Cognitive Core (Inference Fitness)

> **Status:** 🔒 **LOCKED — Stages 0–7 first-slice complete** (operator 2026-08-20 night)  
> **Codename:** `OI-CHAT-INFER0`  
> **Parents:** [`ATLAS_COGNITIVE_UNIFICATION_PLAN.md`](ATLAS_COGNITIVE_UNIFICATION_PLAN.md) ·
> [`ATLAS_LEARNING_INTEGRITY_PLAN.md`](ATLAS_LEARNING_INTEGRITY_PLAN.md) ·
> [`ATLAS_PLATFORM_ARCHITECTURE.md`](ATLAS_PLATFORM_ARCHITECTURE.md)  
> **Does not reopen:** AGENT-1 · SELF0 Phase 5 · LLM places trades · inventing PE/FCF/news ·
> blind concurrency/model bump · “use Ollama as much as possible”

---

## 0. Locked intention

**Observability is not a performance-fix task.** It is the measurement foundation for:

1. Progressively increasing Atlas’s **effective** use of local LLM reasoning  
2. Spending inference where reasoning creates **measurable learning value**  
3. Determining from **workload, quality, latency, and cognitive ROI** when Ollama/model/hardware is limiting  

**Not the goal:** maximize Ollama utilization.  
**Goal:** use as much reasoning as produces genuine learning; prove when more capacity is justified.

**Safety boundary (unchanged):**

- LLM = scientist / reasoner (advice-only)  
- Deterministic engine = controller (state, allocation, tests, goals, hard gates)

### CPU / no-GPU amendment (LOCKED)

Operator hardware has **no GPU**. Expect:

| Fact | Envelope |
|------|----------|
| Short chat joke | ~43–52 s generate |
| Heavy Living RAG compose | can hit 90s+ |
| `interactive_timeout` | **120 s** |
| `max_concurrency` | **1** (not auto-raised) |
| `accelerator` | `cpu` |
| `chat_max_context_chars` | **2400** |

Prefer deterministic routes (glossary, self-model, status) over Ollama. Truncate Living RAG for interactive turns. Stage 7 may *advise* GPU — never auto-apply concurrency or model bumps.

---

## 1. Architecture north star

```text
                         ATLAS
                           │
                 Cognitive Core (knowledge·memory·beliefs·experiences·reasoning)
                           │
                    LLM / Ollama  ← scientist (advice-only) · CPU-slow
                           │
          ┌────────────────┼────────────────┐
       MARKET         ENGINEERING        PERSONAL
          │                │                │
          └────────────────┼────────────────┘
                           ↓
                  experience → learn
```

---

## 2. Stages (LOCKED — first slice)

| Stage | Name | First-slice done when | Status |
|-------|------|----------------------|--------|
| **0** | Observe | Fitness ledger + evening | 🔒 |
| **1** | Stabilize | Timeout 120s CPU; single qwen; lanes; purpose tags | 🔒 |
| **2** | Use LLM meaningfully | Chat/Eng/Market/Research/Personal wired; deterministic-first | 🔒 |
| **3** | Evidence | `scientist_packet` into decide-time rationale | 🔒 |
| **4–5** | Experiments / Learning | Evening cognitive-loop from CU.B learning stories | 🔒 |
| **6** | Cognitive ROI | Purpose spend + scientist vs compose-timeout ratio | 🔒 |
| **7** | Hardware/model limit | Advisory GPU/concurrency gate — **no auto-apply** | 🔒 |

**No blind concurrency increase.** Stage 7 `recommend_concurrency_bump` requires separate operator LOCK before any config change.

---

## 3. Module map

| Module | Role |
|--------|------|
| `atlas/llm/fitness_ledger.py` | Stage 0 |
| `atlas/llm/cpu_policy.py` | CPU-slow + Stage 7 advice |
| `atlas/llm/cognitive_roi.py` | Stage 6 |
| `atlas/investment/scientist_packet.py` | Stage 3 |
| `atlas/investment/cognitive_experiment.py` | Stages 4–5 evening |
| `decide_rationale` + purpose tags | Stage 2 market scientist |
| self-model / glossary | Stage 2 deterministic-first |

---

## 4. Session log (selected)

| # | Result |
|---|--------|
| D1 | direct qwen3:4b joke ~52s |
| T3/T4 | Atlas joke OK ~43–47s |
| T4b | learn-ask timed out 90s → routed to self-model (S2b) |
| **S0–S7** | First-slice package landed with CPU-slow policy |

---

## 5. Operator verify after bounce

```bash
sudo bash scripts/bounce_atlas_stab0.sh
```

1. Joke → OK under 120s (fitness `assistant_compose`)  
2. “What is F&O?” → glossary, no chat fitness row  
3. “What did you learn in markets?” → self-model, fast, no Ollama  
4. Evening mail: fitness + Cognitive ROI + cognitive loop + CPU/hardware gate  

---

## 6. Explicitly NOT done by this lock

- Multi-week live Cognitive ROI proof  
- Auto-raising `max_concurrency` or pulling larger models  
- GPU purchase / install  
- AGENT-1 / SELF0 Phase 5  

Those remain measure-driven follow-ons.

---

*Stages 0–7 first-slice LOCKED under CPU/no-GPU amendment.*
