# Host unattended boot, paper trading, and outage resilience

> **Audience:** operators on this host (`datanode` / jagd)  
> **Status:** configured 2026-07-27; resilience code in Atlas `ir.3` / investor worker v3 / paper trading v2  
> **Related:** [`MISSIONS_OPERATOR_GUIDE.md`](MISSIONS_OPERATOR_GUIDE.md), [`AUTONOMOUS_INVESTMENT_LEARNER_PLAN.md`](AUTONOMOUS_INVESTMENT_LEARNER_PLAN.md)

This note records what we set up so Atlas comes back after power / Wi‑Fi / process loss, how the India equity learner book is wired, and how trading + emails behave when the internet is flaky.

---

## 1. Host: auto-power, Wi‑Fi, login, Atlas systemd

Ran (once, with sudo):

```bash
sudo bash /data/atlas/deploy/host_unattended_boot.sh --watchdog
```

That configured:

| Layer | What |
|-------|------|
| NetworkManager wait-online | Atlas unit waits for network before start |
| Wi‑Fi autoconnect | Saved SSIDs (e.g. phone hotspot names) reconnect without a click |
| GDM AutomaticLogin | User `jagd` — desktop session without password prompt after boot |
| `atlas.service` | Enabled at `multi-user.target`; copies `/data/atlas/.env` → `/etc/atlas/atlas.env` |
| `atlas-watchdog.timer` | Every ~5 minutes; restarts Atlas if the unit is unexpectedly inactive |

### Day-to-day commands

```bash
sudo systemctl status atlas
sudo systemctl stop atlas      # intentional stop — stays down until start
sudo systemctl start atlas
sudo systemctl restart atlas
journalctl -u atlas -f
systemctl is-active atlas
curl -sS http://127.0.0.1:8000/health
```

**Do not** also run `atlas serve` in a terminal while the unit is active — that fights for ports/RAM.

### Still manual (BIOS)

Confirm **Restore on AC Power Loss / Always On** in BIOS so the PC powers itself after outages.

---

## 2. Paper trading book (why evening had 0 fills before)

Root causes on 2026-07-27 evening digest:

1. Mission config had been operator-edited to a single symbol / wrong book (not `india_equity_learner`).
2. Most ticks were **outside NSE hours** (`before_open` / `after_close` / weekend).
3. Live Yahoo bars often empty during internet drops → ranking/trading cold-start.
4. Atlas process had been stopped; systemd alone does not restart an *intentional* `stop` until watchdog / start.

**Fixed config direction:** Decision Simulation / paper mission uses:

- `portfolio_key=india_equity_learner`
- empty `instruments` → auto NIFTY50 / M0 universe
- `feed_mode=live` (Yahoo)
- research gate soft MoS for learner books

Holdings and cash live in the **sim portfolio ledger (Postgres)** — they are **not wiped** when the host is offline for days. On resume, live ticks mark prices on existing positions and continue research / decisions / learning.

---

## 3. Outage resilience (software)

### Emails (Investor Reports)

- Dedup key is **IST calendar day** (not UTC).
- Sent flags are durable under `{data}/market/investor_reports_sent.json`.
- **SMTP failure does not mark the day as sent** — retry when mail works again.
- **Catch-up:** if the morning (07–10 IST) or evening (15:45–18 IST) window was missed (offline / Atlas down / no internet), the next weekday tick **before 23:00 IST** still sends **once** for that IST day, with a “catch-up” note in the body.
- Multi-day offline: we catch up **today’s** morning/evening when back; we do not invent backfilled digests for past IST days.

### Evening honesty (zero fills)

Evening mail now includes **Why no fills** when the day’s ledger has no IST fills, using counters from:

`{data}/market/session_notes/{portfolio_key}/{ist_date}.json`

Typical buckets: `session_closed`, `empty_live_feed`, `research_hold`, `strategy_hold`, `feed_error`, etc. Optional `feed_gap_days` notes that prices resumed after a multi-day gap while **positions were kept**.

### Trading resume

When internet returns during an open NSE cash session:

1. Live bars load again.
2. Existing positions are marked to market.
3. Strategy + research gate run as usual; fills only when signals + gates allow.
4. Learning / IRA dossiers continue from durable store.

No dedicated WAN yet: treat intermittent connectivity as normal; Atlas must be **patient**, not reset the book.

---

## 4. Does trading start tomorrow when markets are live?

**Yes — if all of the following hold:**

1. `systemctl is-active atlas` → `active` (systemd + watchdog).
2. Internet / Wi‑Fi up during **NSE cash hours ~09:15–15:30 IST** (Mon–Fri, excluding holidays).
3. Paper / Decision Simulation mission still on `india_equity_learner` with live feed + auto universe.
4. You are **not** running a second `atlas serve` that conflicts.

Expect:

- Marks and research ticks even with few or zero fills (research gate / strategy hold is normal).
- Morning email ~07–10 IST (or catch-up later that day).
- Evening email after ~15:45 IST (or catch-up later that day).
- **No fills while the market is closed** — that is correct, not a bug.

First useful session after this setup: **next NSE open**.

---

## 5. Quick verify checklist

```bash
systemctl is-active atlas
curl -sS http://127.0.0.1:8000/health
# Mission / portfolio: india_equity_learner on Decision Simulation
# Optional: journalctl -u atlas -f during market hours
```

After any intentional `systemctl stop atlas`, start it again when you want recovery; the watchdog is for unexpected death, not permanent operator stop (behavior depends on watchdog script — prefer `restart` / `start` when you want it up).
