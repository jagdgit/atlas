# Operator Communication Service (locked design)

**Status:** Design lock — implement in phases.  
**Not** a new top-level OS. Platform capability used by Market, Engineering, Personal, Resource OS, solar-plant, etc.  
**Date:** 2026-07-26

---

## 1. Problem

Atlas needs to talk to the **Operator** (you) with the right *urgency* and *channel*.  
Today we have a Phase-0 **Notifier** (SSE + optional SMTP for `*.failed` / `*.completed`). That is too coarse for:

- Daily / weekly reports (email)
- Host / security interrupts (push / Telegram)
- Quiet completions (log + Chat UI next open)
- Two-way remote control (“Status”, “Pause Engineering”)

Do **not** ask “email or WhatsApp?” Ask: **when should Atlas interrupt, and through which channel?**

---

## 2. Locked principle

```text
Programs / Resource OS / Missions
        ↓
  notify(operator, severity, kind, payload)
        ↓
Operator Communication Service  (platform)
        ↓
  Chat UI · Email · Telegram · Slack · Push · SMS · Voice (future)
```

- One **abstraction**; Programs never import Slack/Telegram SDKs.
- Solar-plant test: no Market-only coupling inside the communication core.
- Extends / evolves today’s `Notifier` — does **not** replace the durable event bus.

---

## 3. Severity levels (contract)

| Level | Name | Interrupt? | Default channels | Examples |
|------:|------|------------|------------------|----------|
| **0** | Log only | No | `audit.events` / journal | Research tick note, archive root checksum skip, knowledge chunk written |
| **1** | Chat / console | Soft | Web console inbox + SSE | Research finished, 18 eng lessons, backup OK, archive ingest complete |
| **2** | Report | Deferred | **Email** (primary) | Morning investment plan, weekly eng summary, patent watch, daily Atlas digest |
| **3** | Attention | Soon | Telegram/Slack + console | Disk 95%, UPS on battery, security signal, market alert ready |
| **4** | Immediate | Wake | Telegram/Slack + email + (later) push/SMS | Production down, DB corruption, power failure, critical market halt |

Channel matrix is **policy**, not hard-coded in Programs. Operator can mute L2 email for Market but keep L3 Telegram for Host.

---

## 4. Message shape (Admission-style contract)

```text
OperatorMessage
  id, created_at
  severity: 0..4
  kind: report | alert | status | approval_request | digest
  program_id?, mission_id?, worker_id?
  title: str
  body: str | structured blocks
  actions?: [{ id, label, type }]   # e.g. OPEN_REPORT, APPROVE, PAUSE_PROGRAM
  dedupe_key?: str                  # suppress spam
  expires_at?
```

Delivery result per channel: `sent | skipped | failed` (best-effort; never crash the producer).

---

## 5. Channel roadmap (build order)

| Phase | Channel | Purpose | Notes |
|-------|---------|---------|-------|
| **OC-0** | Clarify Notifier | Map today’s SSE/email onto L0–L2 | No new deps |
| **OC-1** | **Email reports** | L2 digests + investor morning/trade | **Shipped path exists** (`EmailSender` + investor reports); generalize |
| **OC-2** | Console inbox | L1 messages when UI opens | Persist undelivered L1 |
| **OC-3** | **Telegram bot** | L3/L4 + two-way commands | Prefer over WhatsApp for personal Atlas |
| **OC-4** | Slack (optional) | Same as Telegram if you already live there | Interactive buttons |
| **OC-5** | Mobile push | Native app | Later |
| **OC-6** | WhatsApp | Personal alerts | Postpone (Meta Business API cost/policy) |
| **OC-7** | SMS / Voice | L4 only | Future |

**Preference for remote control:** Telegram Bot API (excellent, free, phone notifications) before WhatsApp.

---

## 6. Two-way (Operator → Atlas)

Not only push. Inbound commands (Telegram/Slack/Chat) map to a small **command surface**:

| Command | Effect |
|---------|--------|
| `status` | Host + Program + Research + Archive summary |
| `pause <program>` | Pause program members |
| `resume <program>` | Resume |
| `report morning` | Trigger investor / daily digest email |
| `ack <message_id>` | Clear L3 alert |

Commands go through existing Mission/Program APIs + Resource OS admission (never bypass Host Guard).

---

## 7. Relationship to existing pieces

| Existing | Role after OC |
|----------|----------------|
| `audit.events` + dispatcher | Durability / L0 source of truth |
| `Notifier` + SSE | Becomes **web channel adapter** under OC |
| `EmailSender` | **Email channel adapter**; investor reports call `notify(severity=2, kind=report)` |
| Investor morning/trade mail | First **L2 report** consumers (Market Program) |
| Ops dashboard | Shows L1 inbox + recent L3 |

**Do not** invent a Market-only mailer long-term — Market raises OC messages; OC routes to email.

---

## 8. Explicit non-goals

- New top-level “Communication OS”
- WhatsApp as v1
- Interrupting the operator for every archive tick (L0)
- Programs selecting SMTP hosts themselves
- Replacing Chat UI with Telegram

---

## 9. Implementation sketch (when coding starts)

```text
atlas/notify/          # evolve, don't fork
  service.py           # Notifier → OperatorCommunication façade
  severity.py          # L0–L4 policy
  channels/
    web.py             # SSE + console inbox
    email.py           # existing EmailSender
    telegram.py        # OC-3
    slack.py           # OC-4
  commands.py          # inbound command router
```

Config / env (illustrative):

```bash
ATLAS_OC_EMAIL_SEVERITY_MIN=2
ATLAS_OC_TELEGRAM_BOT_TOKEN=
ATLAS_OC_TELEGRAM_CHAT_ID=
ATLAS_OC_SLACK_WEBHOOK=
```

---

## 10. Near-term tickets

1. **OC-UX1** — Archive cards: ingest complete vs running; learned totals; Stop frees slot ✅ (this session)
2. **OC-1a** — Generalize investor email into `notify(severity=2, kind=report)` without breaking Market UI
3. **OC-2** — Persist L1 console inbox (`GET /v1/operator/inbox`)
4. **OC-3** — Telegram bot: L3 host alerts + `status` command
5. **OC-Policy** — Per-program mute / channel preferences in config

---

## 11. Frozen decisions

| # | Decision |
|---|----------|
| **OC1** | Operator Communication is a **platform service**, not a Program feature |
| **OC2** | Urgency is first-class (**L0–L4**); channels are adapters |
| **OC3** | Email first for reports; Telegram preferred over WhatsApp for alerts |
| **OC4** | Two-way remote control is in-scope for OC-3+ |
| **OC5** | No new top-level OS name |
| **OC6** | Durable events remain the log; OC is delivery policy on top |

---

## 12. How this answers “Archive complete” messaging

| Event | Severity | Channel today / soon |
|-------|----------|----------------------|
| File batch progress | L0 | Journal / checkpoint only |
| Archive ingest complete | L1 (+ optional L2 email digest) | Console badge + optional email |
| Archive slot blocked / disk high | L3 | Telegram/email when OC-3 lands |

Same pattern for Market trade reports (L2 email — already prototyping) and Host Guard pressure (L3).
