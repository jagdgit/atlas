"""Loop 0 — Operational Health (O1–O5).

Fail closed, recover automatically, and fail loudly when recovery is not successful.

Runs inside the existing provider-health tick (``provider_health_tick``, every 120 s). Each tick:

* **O2** detects a Zerodha login recovery (provider not READY → READY), invalidates and refreshes
  the provider-dependent NFO masters, then records ``FNO_LAB_READY`` or ``FNO_DEGRADED`` naming
  the exact dependency that is still failing.
* **O1** classifies the F&O lab during its expected operating window into one of five idle
  categories (A genuine idle, B safety-blocked, C capability-blocked, D infrastructure failure,
  E worker/scheduler failure), opens an incident for C/D/E, attempts recovery (max 3), and emails
  the operator by severity: P0 as soon as recovery is exhausted, P1 only after the failure
  persisted, P2 in the evening digest only.
* **O4** flags safety blocks that become systemic (one block tag ≥60 % of actionable buys for
  ≥2 consecutive sessions). Gates are never weakened — the alert asks for investigation.
* **O5** writes failure → cause → recovery → outcome → lesson to an experience ledger when an
  incident closes.

Never on the order path, never places or modifies orders, never changes strategy or gates.
Reads persisted artifacts only (packs, pipeline, provider health, NFO master state).
"""

from __future__ import annotations

import json
import logging
import uuid
from collections import Counter
from datetime import date, datetime, time as dtime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

_log = logging.getLogger("atlas.investment.ops_health")
_IST = ZoneInfo("Asia/Kolkata")

VERSION = "ops.health.v1"
STORE_REL = Path("investment") / "ops_health"
FNO_LAB = "india_fno_learner"
# Optional bootstrap-bound resume for Phase-5 stale F&O paper worker.
_paper_worker_resume: Callable[[], dict[str, Any]] | None = None


def bind_paper_worker_resume(fn: Callable[[], dict[str, Any]] | None) -> None:
    """Wire WorkerManager.resume for the accidental Phase-5 F&O pause only."""
    global _paper_worker_resume
    _paper_worker_resume = fn
EQUITY_LAB = "india_equity_learner"
SUBJECT_PREFIX = "[Atlas OPS]"

IDLE_GENUINE = "A_GENUINE_IDLE"
IDLE_SAFETY = "B_SAFETY_BLOCKED"
IDLE_CAPABILITY = "C_CAPABILITY_BLOCKED"
IDLE_INFRA = "D_INFRASTRUCTURE_FAILURE"
IDLE_WORKER = "E_WORKER_SCHEDULER_FAILURE"
OPERATING = "OPERATING"

P0 = "P0"
P1 = "P1"
P2 = "P2"

FNO_LAB_READY = "FNO_LAB_READY"
FNO_DEGRADED = "FNO_DEGRADED"

MAX_RECOVERY_ATTEMPTS = 3
RECOVERY_SPACING_S = 90.0
CONFIRM_WINDOW_S = 10 * 60.0
P1_PERSIST_S = 20 * 60.0
PACK_STALE_S = 60 * 60.0
RESOLVED_GRACE_TICKS = 1
SYSTEMIC_SHARE = 0.60
SYSTEMIC_SESSIONS = 2
SYSTEMIC_MIN_ACTIONABLE = 3
SYSTEMIC_REALERT_DAYS = 3
SCHEDULER_FAIL_ALERT = 3

FNO_WINDOW = (dtime(9, 15), dtime(15, 30))
FNO_MASTER_WATCH_FROM = dtime(8, 45)

_MASTER_REASONS = {
    "instrument_master_missing": "instrument_master",
    "futures_master_missing": "futures_master",
    "futures_master_stale": "futures_master",
    "expiry_missing": "futures_master",
}
_RECOVERABLE = {"instrument_master", "futures_master", "options_master"}
# Worker-side recovery: only the accidental Phase-5 stale pause of the F&O paper lab.
_RECOVERABLE_WORKER = {"fno_paper_worker"}
_PHASE5_STALE_MARKER = "phase5:STALE"
STATUS_OPEN = "OPEN"
STATUS_RESOLVED = "RESOLVED"
STATUS_UNRESOLVED = "UNRESOLVED_OPERATOR_ACTION_REQUIRED"
STATUS_RECOVERED_VERIFIED = "RECOVERED_VERIFIED"
_USABLE_MASTER = {"READY", "EMPTY_VALID"}
_PIPELINE_ACTIONABLE = (
    "authorized_buy",
    "plc_a_incomplete",
    "research_hold",
    "mos_unavailable",
    "mos_negative",
    "lab_policy_avoid",
)
_PIPELINE_TAG = {
    "plc_a_incomplete": "fundamentals_incomplete",
    "research_hold": "research_forced_hold",
    "mos_unavailable": "mos_unavailable",
    "mos_negative": "mos_negative",
    "lab_policy_avoid": "lab_policy_hold",
}

LESSONS = {
    "futures_master": (
        "An empty futures response following provider failure must not become a valid day cache; "
        "only a successful fetch is cached, and a new login invalidates provider-dependent caches."
    ),
    "options_master": (
        "An options master is only valid when it comes from a successful NFO dump; retry after "
        "backoff instead of pinning an empty chain."
    ),
    "instrument_master": (
        "Without an instrument master no F&O contract can be resolved; refresh it right after "
        "login, before the session opens."
    ),
    "zerodha_provider": (
        "Live-required labs pause while the provider is degraded; recovery is confirmed by a "
        "fresh LTP probe, not by the absence of errors."
    ),
    "fno_paper_worker": (
        "Packs that stop updating during the session mean the worker is not ticking; detect it "
        "from artifact freshness, not from the worker's own report."
    ),
    "scheduler": (
        "A task that fails permanently is silent work loss; every permanent failure must be "
        "counted and surfaced the same day."
    ),
    "fno_capability": (
        "A lab-wide NOT_READY rate with healthy masters is a capability gap; record it as a "
        "named gap instead of an idle session."
    ),
}


# --- time / paths ---------------------------------------------------------------------


def _now_utc(now: datetime | None = None) -> datetime:
    clock = now if isinstance(now, datetime) else datetime.now(timezone.utc)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=timezone.utc)
    return clock.astimezone(timezone.utc)


def _ist(now: datetime | None = None) -> datetime:
    return _now_utc(now).astimezone(_IST)


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        ts = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def is_trading_day(day: date) -> bool:
    if day.weekday() >= 5:
        return False
    try:
        from atlas.trading.holidays import is_holiday

        return not is_holiday("nse_equity", day)
    except Exception:  # noqa: BLE001
        return True


def fno_window_open(now: datetime | None = None) -> bool:
    ist = _ist(now)
    return is_trading_day(ist.date()) and FNO_WINDOW[0] <= ist.time() < FNO_WINDOW[1]


def _root(data_dir: str | Path) -> Path:
    return Path(data_dir) / STORE_REL


def state_path(data_dir: str | Path, day: str) -> Path:
    return _root(data_dir) / f"{day}.json"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _write_json(path: Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, indent=2, default=str) + "\n", encoding="utf-8")
    tmp.replace(path)


def load_state(data_dir: str | Path, day: str) -> dict[str, Any]:
    doc = _read_json(state_path(data_dir, day))
    doc.setdefault("version", VERSION)
    doc.setdefault("ist_day", day)
    doc.setdefault("incidents", {})
    doc.setdefault("events", [])
    doc.setdefault("alerts", [])
    doc.setdefault("windows", {})
    return doc


# --- scheduler permanent failures (category E) -----------------------------------------


def record_task_failure(
    data_dir: str | Path | None,
    *,
    task_type: str,
    task_id: str,
    error: str,
    now: datetime | None = None,
) -> None:
    """Called by the scheduler when a task fails permanently (after its retries)."""
    if not data_dir:
        return
    ist = _ist(now)
    row = {
        "ts": _now_utc(now).isoformat(),
        "ist_day": ist.date().isoformat(),
        "task_type": str(task_type),
        "task_id": str(task_id),
        "error": str(error)[:300],
    }
    path = _root(data_dir) / "task_failures.jsonl"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")
    except OSError:
        _log.debug("task failure record failed", exc_info=True)


def task_failures_for_day(data_dir: str | Path, day: str) -> list[dict[str, Any]]:
    path = _root(data_dir) / "task_failures.jsonl"
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict) and row.get("ist_day") == day:
                out.append(row)
    except OSError:
        return []
    return out


# --- F&O assessment (O1) ---------------------------------------------------------------


def load_fno_packs(data_dir: str | Path, day: str) -> list[dict[str, Any]]:
    root = Path(data_dir) / "investment" / "fno" / "packs"
    if not root.is_dir():
        return []
    packs = []
    for path in sorted(root.glob(f"*_{day}.json")):
        doc = _read_json(path)
        if doc:
            packs.append(doc)
    return packs


def load_nfo_master_state(data_dir: str | Path) -> dict[str, Any]:
    from atlas.investment.zerodha_feed import NFO_STATE_REL

    return _read_json(Path(data_dir) / NFO_STATE_REL)


def _master_state_today(nfo: dict[str, Any], kind: str, day: str) -> dict[str, Any]:
    entry = nfo.get(kind) if isinstance(nfo.get(kind), dict) else {}
    if entry and entry.get("ist_day") != day:
        return {"state": "NOT_ATTEMPTED", "reason": "no_fetch_today", "last_ist_day": entry.get("ist_day")}
    return entry or {"state": "NOT_ATTEMPTED"}


def _finding(
    key: str,
    *,
    category: str,
    severity: str,
    dependency: str,
    what: str,
    why: str,
    impact: str,
    lab: str = FNO_LAB,
    actions: list[str] | None = None,
    alert_owner: str | None = None,
    detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "key": key,
        "lab": lab,
        "category": category,
        "severity": severity,
        "dependency": dependency,
        "what": what,
        "why": why,
        "impact": impact,
        "actions": actions or [],
        "alert_owner": alert_owner,
        "detail": detail or {},
        "recoverable": dependency in _RECOVERABLE or dependency in _RECOVERABLE_WORKER,
    }


def assess_fno(
    data_dir: str | Path,
    *,
    health: dict[str, Any],
    now: datetime | None = None,
    packs: list[dict[str, Any]] | None = None,
    nfo_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Classify the F&O lab right now. Returns ``{category, findings, summary}``."""
    ist = _ist(now)
    day = ist.date().isoformat()
    trading = is_trading_day(ist.date())
    in_window = trading and FNO_WINDOW[0] <= ist.time() < FNO_WINDOW[1]
    watch_masters = trading and FNO_MASTER_WATCH_FROM <= ist.time() < FNO_WINDOW[1]
    packs = load_fno_packs(data_dir, day) if packs is None else packs
    nfo = load_nfo_master_state(data_dir) if nfo_state is None else nfo_state
    fut = _master_state_today(nfo, "futures", day)
    opt = _master_state_today(nfo, "options", day)
    ready = [p for p in packs if str(p.get("status")) == "READY"]
    reasons = Counter(str(p.get("reason") or "unknown") for p in packs if str(p.get("status")) != "READY")
    dominant, dominant_n = (reasons.most_common(1)[0] if reasons else (None, 0))
    latest = max((_parse_ts(p.get("as_of")) for p in packs if _parse_ts(p.get("as_of"))), default=None)
    provider = str(health.get("status") or "UNKNOWN")
    summary = {
        "ist_day": day,
        "at": _now_utc(now).isoformat(),
        "expected_window": in_window,
        "provider_status": provider,
        "futures_master": fut.get("state"),
        "options_master": opt.get("state"),
        "packs": len(packs),
        "packs_ready": len(ready),
        "dominant_reason": dominant,
        "dominant_count": dominant_n,
        "latest_pack_at": latest.isoformat() if latest else None,
    }
    findings: list[dict[str, Any]] = []
    impact_all = (
        f"{len(packs) - len(ready)}/{len(packs)} F&O packs NOT_READY"
        + (f" (dominant: {dominant})" if dominant else "")
        + ". No F&O experiment can run until this clears."
    )

    if provider in {"LOGIN_REQUIRED", "EXPIRED"} and (in_window or watch_masters):
        findings.append(
            _finding(
                "fno:zerodha_login",
                category=IDLE_INFRA,
                severity=P0,
                dependency="zerodha_login",
                what=f"Zerodha session = {provider}",
                why="No valid Kite Connect access_token for today.",
                impact="Live-required labs (F&O, intraday) are paused.",
                actions=["Reply to the Zerodha login email with a fresh request_token, or open /zerodha/login."],
                alert_owner="mdph_login_email",
            )
        )
    elif provider in {"ERROR", "DEGRADED"} and in_window:
        findings.append(
            _finding(
                "fno:zerodha_provider",
                category=IDLE_INFRA,
                severity=P1,
                dependency="zerodha_provider",
                what=f"Zerodha provider = {provider}",
                why=str(health.get("last_ltp_error") or health.get("message") or "LTP probe failing"),
                impact="Live-required labs are paused while the provider is degraded.",
                actions=["Check Kite status; if the token was revoked, re-login via /zerodha/force-login."],
            )
        )

    provider_ok = provider == "READY"
    if provider_ok and watch_masters:
        fut_state = str(fut.get("state") or "NOT_ATTEMPTED")
        opt_state = str(opt.get("state") or "NOT_ATTEMPTED")
        pack_master_dep = _MASTER_REASONS.get(str(dominant)) if packs and not ready else None
        if fut_state not in _USABLE_MASTER and (fut_state != "NOT_ATTEMPTED" or in_window):
            stale = fut_state == "READY_STALE"
            findings.append(
                _finding(
                    "fno:futures_master",
                    category=IDLE_INFRA,
                    severity=P1 if stale else P0,
                    dependency="futures_master",
                    what=(
                        f"Futures master = STALE ({fut.get('stale_ist_day')})"
                        if stale
                        else f"Futures master = {fut_state}"
                    ),
                    why=f"NFO futures fetch: {fut.get('reason') or 'not fetched today'}.",
                    impact=impact_all if packs else "F&O expiry/contract resolution is unavailable.",
                    actions=[
                        "Usually no action: Atlas retries automatically.",
                        "If Zerodha was re-logged in, nothing else is needed; otherwise re-login via /zerodha/force-login.",
                    ],
                    detail={"futures": fut},
                )
            )
        elif pack_master_dep and in_window:
            findings.append(
                _finding(
                    f"fno:{pack_master_dep}",
                    category=IDLE_INFRA,
                    severity=P0,
                    dependency=pack_master_dep,
                    what=f"{len(packs)}/{len(packs)} packs blocked by {dominant}",
                    why=f"Packs report {dominant} while the master state reads futures={fut_state}, options={opt_state}.",
                    impact=impact_all,
                    actions=["Usually no action: Atlas refreshes the NFO masters automatically."],
                )
            )
        if opt_state not in _USABLE_MASTER and fut_state in _USABLE_MASTER and in_window:
            findings.append(
                _finding(
                    "fno:options_master",
                    category=IDLE_INFRA,
                    severity=P0,
                    dependency="options_master",
                    what=f"Options master = {opt_state}",
                    why=f"NFO options fetch: {opt.get('reason') or 'not fetched today'}.",
                    impact="ATM CE/PE cannot be resolved; F&O packs cannot become READY.",
                    actions=["Usually no action: Atlas retries automatically."],
                    detail={"options": opt},
                )
            )

    if in_window and provider_ok and ist.time() >= dtime(10, 15):
        stale_for = (_now_utc(now) - latest).total_seconds() if latest else None
        if stale_for is None or stale_for > PACK_STALE_S:
            findings.append(
                _finding(
                    "fno:paper_worker",
                    category=IDLE_WORKER,
                    severity=P0,
                    dependency="fno_paper_worker",
                    what=(
                        "No F&O pack written today"
                        if latest is None
                        else f"Last F&O pack {int(stale_for // 60)} min ago"
                    ),
                    why="The F&O paper worker is not completing ticks during the session.",
                    impact="The F&O lab is not evaluating anything.",
                    actions=["Check `systemctl status atlas` and the worker list; restart the service if workers are stopped."],
                )
            )

    has_infra = any(f["category"] in {IDLE_INFRA, IDLE_WORKER} for f in findings)
    if in_window and packs and not ready and not has_infra:
        findings.append(
            _finding(
                "fno:capability",
                category=IDLE_CAPABILITY,
                severity=P1,
                dependency="fno_capability",
                what=f"0/{len(packs)} F&O packs READY (dominant: {dominant})",
                why=f"Masters and provider are healthy; packs fail on {dominant}.",
                impact="Lab-wide capability gap: no F&O decision can be evaluated.",
                actions=["No action needed now; recorded as a capability gap for review."],
            )
        )

    if findings:
        cats = [f["category"] for f in findings]
        category = next(c for c in (IDLE_WORKER, IDLE_INFRA, IDLE_CAPABILITY) if c in cats)
    elif not in_window:
        category = IDLE_GENUINE
    elif ready:
        category = OPERATING
    else:
        category = IDLE_SAFETY if packs else IDLE_GENUINE
    summary["category"] = category
    return {"category": category, "findings": findings, "summary": summary}


def _pack_written_since_open(summary: dict[str, Any], incident: dict[str, Any]) -> bool:
    latest = _parse_ts(summary.get("latest_pack_at"))
    opened = _parse_ts(incident.get("opened_at"))
    if latest is None:
        return False
    return opened is None or latest > opened


# --- systemic safety blocks (O4) -------------------------------------------------------


def _pipeline_sessions(data_dir: str | Path, lab: str, upto_day: str, limit: int = 10) -> list[dict[str, Any]]:
    root = Path(data_dir) / "investment" / "decisions" / "pipeline" / lab
    if not root.is_dir():
        return []
    days = sorted(p.stem for p in root.glob("*.json") if p.stem <= upto_day)[-limit:]
    out = []
    for d in days:
        doc = _read_json(root / f"{d}.json")
        if doc:
            doc["_day"] = d
            out.append(doc)
    return out


def assess_systemic_blocks(
    data_dir: str | Path,
    *,
    day: str,
    lab: str = EQUITY_LAB,
) -> dict[str, Any]:
    """Share of actionable buys blocked per tag, per session; systemic when persistent."""
    sessions = []
    for doc in _pipeline_sessions(data_dir, lab, day):
        counts = doc.get("counts") if isinstance(doc.get("counts"), dict) else {}
        actionable = sum(int(counts.get(k) or 0) for k in _PIPELINE_ACTIONABLE)
        shares = {}
        for key, tag in _PIPELINE_TAG.items():
            n = int(counts.get(key) or 0)
            if actionable:
                shares[tag] = round(n / actionable, 3)
        symbols: dict[str, list[str]] = {}
        for row in doc.get("rows") or []:
            if isinstance(row, dict) and row.get("final") in _PIPELINE_TAG:
                symbols.setdefault(_PIPELINE_TAG[row["final"]], []).append(str(row.get("symbol")))
        sessions.append(
            {"day": doc["_day"], "actionable": actionable, "shares": shares, "symbols": symbols}
        )
    findings = []
    recent = sessions[-SYSTEMIC_SESSIONS:]
    if len(recent) == SYSTEMIC_SESSIONS and recent[-1]["day"] == day:
        for tag in _PIPELINE_TAG.values():
            if all(
                s["actionable"] >= SYSTEMIC_MIN_ACTIONABLE and s["shares"].get(tag, 0) >= SYSTEMIC_SHARE
                for s in recent
            ):
                run = 0
                for s in reversed(sessions):
                    if s["actionable"] and s["shares"].get(tag, 0) >= SYSTEMIC_SHARE:
                        run += 1
                    else:
                        break
                today = recent[-1]
                findings.append(
                    _finding(
                        f"equity:systemic:{tag}",
                        lab=lab,
                        category=IDLE_SAFETY,
                        severity=P1,
                        dependency=f"gate:{tag}",
                        what=(
                            f"{tag} blocked {today['shares'][tag]:.0%} of actionable buys today "
                            f"({run} consecutive sessions ≥{SYSTEMIC_SHARE:.0%})"
                        ),
                        why=(
                            "The gate is working as designed; the persistence means the inputs it "
                            "needs are missing for most candidates, not that one name is weak."
                        ),
                        impact=(
                            f"{int(round(today['shares'][tag] * today['actionable']))}/{today['actionable']} "
                            f"actionable buys held today ({', '.join(today['symbols'].get(tag, [])[:8])})."
                        ),
                        actions=[
                            "No gate change. Review why the evidence is missing for these names "
                            "(fundamentals acquisition tasks / provider coverage).",
                        ],
                        detail={"sessions": recent, "run_sessions": run},
                    )
                )
    return {"sessions": sessions, "findings": findings}


# --- recovery (O2) ---------------------------------------------------------------------


def _default_feed(data_dir: str | Path) -> Any:
    from atlas.investment.zerodha_feed import ZerodhaMarketFeed

    return ZerodhaMarketFeed.from_env(data_dir=data_dir)


def recover_nfo_masters(data_dir: str | Path, *, feed: Any | None = None) -> dict[str, Any]:
    """Invalidate + refetch futures and options masters; name each dependency's outcome."""
    try:
        feed = feed or _default_feed(data_dir)
        status = feed.refresh_nfo_masters()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "readiness": FNO_DEGRADED, "failed": ["nfo_refresh"], "error": f"{type(exc).__name__}: {exc}"}
    failed = [
        f"{kind}_master"
        for kind in ("futures", "options")
        if str((status.get(kind) or {}).get("state")) not in _USABLE_MASTER
    ]
    return {
        "ok": not failed,
        "readiness": FNO_LAB_READY if not failed else FNO_DEGRADED,
        "failed": failed,
        "masters": status,
    }


# --- email (O1) ------------------------------------------------------------------------


def _ist_hm(ts: Any) -> str:
    parsed = _parse_ts(ts)
    return parsed.astimezone(_IST).strftime("%H:%M") if parsed else "?"


def build_alert(incident: dict[str, Any], *, current: dict[str, Any], day: str) -> tuple[str, str]:
    sev = incident.get("severity") or P1
    plane = "F&O DATA PLANE" if str(incident.get("lab")) == FNO_LAB else "EQUITY SAFETY GATES"
    if str(incident.get("dependency")).startswith("fno_paper") or incident.get("dependency") == "scheduler":
        plane = "WORKERS / SCHEDULER"
    subject = f"{SUBJECT_PREFIX} {sev} ACTION REQUIRED — {plane}: {incident.get('what')} ({day})"
    attempts = incident.get("attempts") or []
    tried = [
        f"  {i}. {_ist_hm(a.get('at'))} {a.get('action')} → {a.get('result')}"
        for i, a in enumerate(attempts, 1)
    ] or ["  (no automatic recovery exists for this failure)"]
    recovery = incident.get("recovery") or "NOT_APPLICABLE"
    state_lines = [f"  {k} = {v}" for k, v in current.items() if v is not None]
    lines = [
        f"ATLAS ACTION REQUIRED — {plane}",
        f"Severity: {sev}",
        f"Day: {day}   Detected: {_ist_hm(incident.get('opened_at'))} IST   Category: {incident.get('category')}",
        "",
        "WHAT FAILED",
        f"  {incident.get('what')}",
        "",
        "WHY",
        f"  {incident.get('why')}",
        "",
        "IMPACT",
        f"  {incident.get('impact')}",
        "",
        "WHAT ATLAS TRIED",
        *tried,
        f"  Automatic recovery: {recovery}",
        "",
        "CURRENT STATE",
        *state_lines,
        "",
        "WHAT YOU CAN DO",
        *[f"  - {a}" for a in (incident.get("actions") or ["No action required; for information."])],
        "",
        "Safety: No orders were submitted. Atlas stays fail-closed (paper only) while this is open.",
    ]
    return subject, "\n".join(lines) + "\n"


def build_resolved(incident: dict[str, Any], *, day: str) -> tuple[str, str]:
    subject = f"{SUBJECT_PREFIX} RESOLVED — {incident.get('what')} ({day})"
    body = "\n".join(
        [
            "ATLAS RECOVERED — no action needed",
            f"Day: {day}",
            f"Failure: {incident.get('what')}",
            f"Opened: {_ist_hm(incident.get('opened_at'))} IST   Resolved: {_ist_hm(incident.get('resolved_at'))} IST",
            f"Recovery: {incident.get('resolution') or incident.get('recovery')}",
            "",
            "Safety: No orders were submitted.",
        ]
    )
    return subject, body + "\n"


def _email_sender() -> Any | None:
    from atlas.investment.zerodha_token_email import _email_sender as mdph_sender

    return mdph_sender()


# --- experience (O5) -------------------------------------------------------------------


def record_experience(data_dir: str | Path, incident: dict[str, Any], *, outcome: str) -> dict[str, Any]:
    dep = str(incident.get("dependency") or "")
    lesson_key = "fno_capability" if dep == "fno_capability" else dep
    if dep.startswith("gate:"):
        lesson = (
            f"A safety gate ({dep[5:]}) that blocks most actionable buys for consecutive sessions "
            "signals missing inputs; investigate the evidence pipeline, never the gate."
        )
    else:
        lesson = LESSONS.get(lesson_key) or "Record the failure, the recovery, and what made it observable."
    row = {
        "version": VERSION,
        "kind": "operational_experience",
        "id": incident.get("id"),
        "ist_day": incident.get("ist_day"),
        "lab": incident.get("lab"),
        "failure": incident.get("what"),
        "cause": incident.get("why"),
        "category": incident.get("category"),
        "severity": incident.get("severity"),
        "recovery": [f"{a.get('action')} → {a.get('result')}" for a in incident.get("attempts") or []],
        "outcome": outcome,
        "alerted": bool(incident.get("alerted_at")),
        "opened_at": incident.get("opened_at"),
        "closed_at": incident.get("resolved_at") or _now_utc().isoformat(),
        "lesson": lesson,
    }
    path = _root(data_dir) / "experience.jsonl"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, default=str) + "\n")
    except OSError:
        _log.debug("ops experience write failed", exc_info=True)
    return row


# --- tick -------------------------------------------------------------------------------


def _event(state: dict[str, Any], kind: str, now: datetime | None, **fields: Any) -> None:
    state["events"].append({"at": _now_utc(now).isoformat(), "event": kind, **fields})
    state["events"] = state["events"][-200:]


def _send(sender: Any, subject: str, body: str) -> bool:
    try:
        return bool(sender.send(subject, body))
    except Exception:  # noqa: BLE001
        _log.warning("ops alert send failed", exc_info=True)
        return False


def ops_health_tick(
    data_dir: str | Path | None,
    health: dict[str, Any],
    *,
    now: datetime | None = None,
    feed: Any | None = None,
    sender: Any | None = None,
    sender_factory: Callable[[], Any] | None = None,
    email: bool = True,
    resume_paper_worker: Callable[[], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """One Loop 0 pass. Never raises; never touches orders."""
    if not data_dir:
        return {"ok": False, "reason": "no_data_dir"}
    try:
        return _tick(
            Path(data_dir), health or {}, now=now, feed=feed, sender=sender,
            sender_factory=sender_factory or _email_sender, email=email,
            resume_paper_worker=resume_paper_worker or _paper_worker_resume,
        )
    except Exception as exc:  # noqa: BLE001
        _log.warning("ops health tick failed: %s", exc, exc_info=True)
        return {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}


def _tick(
    data_dir: Path,
    health: dict[str, Any],
    *,
    now: datetime | None,
    feed: Any | None,
    sender: Any | None,
    sender_factory: Callable[[], Any],
    email: bool,
    resume_paper_worker: Callable[[], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    clock = _now_utc(now)
    ist = _ist(now)
    day = ist.date().isoformat()
    state = load_state(data_dir, day)
    state["ticks"] = int(state.get("ticks") or 0) + 1
    provider = str(health.get("status") or "UNKNOWN")
    prev_provider = state.get("provider_status")

    # O2 — login recovered → invalidate provider caches → refresh masters → readiness.
    if provider == "READY" and prev_provider not in (None, "READY"):
        result = recover_nfo_masters(data_dir, feed=feed)
        state["fno_readiness"] = {
            "at": clock.isoformat(),
            "readiness": result["readiness"],
            "failed": result.get("failed"),
            "trigger": "ZERODHA_LOGIN_RECOVERED",
        }
        _event(
            state, "ZERODHA_LOGIN_RECOVERED", now, previous=prev_provider,
            readiness=result["readiness"], failed=result.get("failed"),
        )
    state["provider_status"] = provider

    fno = assess_fno(data_dir, health=health, now=now)
    systemic = assess_systemic_blocks(data_dir, day=day) if ist.time() >= dtime(15, 30) or not fno_window_open(now) else {"findings": []}
    failures = task_failures_for_day(data_dir, day)
    findings = list(fno["findings"]) + list(systemic.get("findings") or [])
    if len(failures) >= SCHEDULER_FAIL_ALERT:
        types = Counter(str(f.get("task_type")) for f in failures)
        errors = Counter(str(f.get("error"))[:90] for f in failures)
        findings.append(
            _finding(
                "ops:scheduler_failures",
                lab="atlas",
                category=IDLE_WORKER,
                severity=P1,
                dependency="scheduler",
                what=f"{len(failures)} scheduled tasks failed permanently today",
                why="; ".join(f"{e} ×{n}" for e, n in errors.most_common(3)),
                impact="Task types: " + ", ".join(f"{t} ×{n}" for t, n in types.most_common(5)),
                actions=["Review the failing task type in the service log; Atlas cannot repair code errors itself."],
            )
        )

    window = state["windows"].setdefault(FNO_LAB, {"minutes": {}, "first_seen": clock.isoformat()})
    cat = fno["category"]
    if fno["summary"].get("expected_window"):
        window["minutes"][cat] = round(float(window["minutes"].get(cat) or 0) + 2.0, 1)
    window["last"] = fno["summary"]

    current = {
        "provider": provider,
        "futures_master": fno["summary"].get("futures_master"),
        "options_master": fno["summary"].get("options_master"),
        "packs_ready": f"{fno['summary'].get('packs_ready')}/{fno['summary'].get('packs')}",
        "dominant_pack_reason": fno["summary"].get("dominant_reason"),
        "fno_readiness": (state.get("fno_readiness") or {}).get("readiness"),
    }

    incidents: dict[str, Any] = state["incidents"]
    seen = set()
    for f in findings:
        key = f["key"]
        seen.add(key)
        inc = incidents.get(key)
        if inc is None or inc.get("status") in {
            STATUS_RESOLVED,
            STATUS_RECOVERED_VERIFIED,
            STATUS_UNRESOLVED,
        }:
            if inc is not None and (
                f["key"].startswith("equity:systemic:") or f["key"] == "fno:paper_worker"
            ):
                inc["status"] = STATUS_OPEN
                inc.pop("resolved_at", None)
                inc.pop("resolution", None)
                if f["recoverable"]:
                    inc["recovery"] = "PENDING"
            else:
                inc = {
                    "id": uuid.uuid4().hex[:12],
                    "ist_day": day,
                    "opened_at": clock.isoformat(),
                    "status": STATUS_OPEN,
                    "attempts": [],
                    "recovery": "PENDING" if f["recoverable"] else "NOT_APPLICABLE",
                }
                incidents[key] = inc
                _event(state, "INCIDENT_OPENED", now, key=key, severity=f["severity"], category=f["category"])
        inc.update({k: f[k] for k in ("lab", "category", "severity", "dependency", "what", "why", "impact", "actions", "alert_owner")})
        inc["last_seen"] = clock.isoformat()
        inc["missing_ticks"] = 0

        if f["recoverable"] and inc["recovery"] in {"PENDING", "IN_PROGRESS", "RECOVERED_PENDING_CONFIRM"}:
            last = _parse_ts((inc["attempts"][-1] if inc["attempts"] else {}).get("at"))
            spacing = CONFIRM_WINDOW_S if inc["recovery"] == "RECOVERED_PENDING_CONFIRM" else RECOVERY_SPACING_S
            due = last is None or (clock - last).total_seconds() >= spacing
            if due and len(inc["attempts"]) >= MAX_RECOVERY_ATTEMPTS:
                inc["recovery"] = "EXHAUSTED"
            elif due and f["dependency"] in _RECOVERABLE_WORKER:
                # Only resume the accidental Phase-5 stale pause. Other pauses stay operator-owned.
                if resume_paper_worker is None:
                    inc["attempts"].append(
                        {
                            "at": clock.isoformat(),
                            "action": "resume F&O paper worker",
                            "result": "FAILED (no resume binder)",
                        }
                    )
                    inc["recovery"] = (
                        "EXHAUSTED"
                        if len(inc["attempts"]) >= MAX_RECOVERY_ATTEMPTS
                        else "IN_PROGRESS"
                    )
                else:
                    try:
                        result = resume_paper_worker() or {}
                    except Exception as exc:  # noqa: BLE001
                        result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
                    reason = str(result.get("pause_reason") or result.get("reason") or "")
                    allowed = (not reason) or _PHASE5_STALE_MARKER in reason or result.get(
                        "phase5_stale"
                    )
                    ok = bool(result.get("ok")) and bool(allowed)
                    outcome = (
                        "OK"
                        if ok
                        else "FAILED ("
                        + str(
                            result.get("error")
                            or ("pause_reason_not_phase5_stale" if not allowed else "resume_failed")
                        )
                        + ")"
                    )
                    inc["attempts"].append(
                        {
                            "at": clock.isoformat(),
                            "action": "resume F&O paper worker",
                            "result": outcome,
                        }
                    )
                    if ok:
                        inc["recovery"] = "RECOVERED_PENDING_CONFIRM"
                    elif len(inc["attempts"]) >= MAX_RECOVERY_ATTEMPTS:
                        inc["recovery"] = "EXHAUSTED"
                    else:
                        inc["recovery"] = "IN_PROGRESS"
            elif due:
                result = recover_nfo_masters(data_dir, feed=feed)
                outcome = "OK" if result["ok"] else "FAILED (" + ", ".join(result.get("failed") or [result.get("error") or "?"]) + ")"
                inc["attempts"].append({"at": clock.isoformat(), "action": "refresh NFO masters", "result": outcome})
                state["fno_readiness"] = {
                    "at": clock.isoformat(), "readiness": result["readiness"],
                    "failed": result.get("failed"), "trigger": key,
                }
                if result["ok"]:
                    inc["recovery"] = "RECOVERED_PENDING_CONFIRM"
                elif len(inc["attempts"]) >= MAX_RECOVERY_ATTEMPTS:
                    inc["recovery"] = "EXHAUSTED"
                else:
                    inc["recovery"] = "IN_PROGRESS"

        # Packs present while a paper-worker incident is pending confirm → verified recovery.
        if (
            key == "fno:paper_worker"
            and _pack_written_since_open(fno["summary"], inc)
            and inc.get("recovery") in {"RECOVERED_PENDING_CONFIRM", "IN_PROGRESS", "PENDING"}
        ):
            inc["status"] = STATUS_RECOVERED_VERIFIED
            inc["recovery"] = "RECOVERED"
            inc["resolution"] = "pack_write_confirmed"
            inc["resolved_at"] = clock.isoformat()
            _event(state, "INCIDENT_RESOLVED", now, key=key, resolution=inc["resolution"])

        if inc.get("alerted_at") or inc.get("alert_owner"):
            continue
        if f["severity"] == P2:
            continue
        recovery_done = inc["recovery"] in {"EXHAUSTED", "NOT_APPLICABLE"}
        if not recovery_done:
            continue
        persisted = (clock - (_parse_ts(inc["opened_at"]) or clock)).total_seconds()
        if f["severity"] == P1 and persisted < P1_PERSIST_S:
            continue
        if f["key"].startswith("equity:systemic:"):
            last_alert = state.get("systemic_alerted", {}).get(f["key"]) or _last_systemic_alert(data_dir, f["key"], day)
            if last_alert and (ist.date() - date.fromisoformat(last_alert)).days < SYSTEMIC_REALERT_DAYS:
                inc["alert_suppressed"] = f"alerted {last_alert}"
                continue
        if not email:
            inc["alert_suppressed"] = "email_disabled"
            continue
        sender = sender if sender is not None else sender_factory()
        if sender is None:
            inc["alert_suppressed"] = "email_not_configured"
            continue
        subject, body = build_alert(inc, current=current, day=day)
        if _send(sender, subject, body):
            inc["alerted_at"] = clock.isoformat()
            state["alerts"].append({"at": clock.isoformat(), "key": key, "severity": f["severity"], "subject": subject})
            if f["key"].startswith("equity:systemic:"):
                state.setdefault("systemic_alerted", {})[f["key"]] = day
            _event(state, "ALERT_SENT", now, key=key, severity=f["severity"])

    for key, inc in incidents.items():
        if key in seen or inc.get("status") in {
            STATUS_RESOLVED,
            STATUS_UNRESOLVED,
            STATUS_RECOVERED_VERIFIED,
        }:
            continue
        # A resume alone is not verification — a pack written after the incident opened is.
        if key == "fno:paper_worker" and _pack_written_since_open(fno["summary"], inc):
            inc["status"] = STATUS_RECOVERED_VERIFIED
            inc["resolved_at"] = clock.isoformat()
            inc["resolution"] = "pack_write_confirmed"
            if inc.get("recovery") in {"RECOVERED_PENDING_CONFIRM", "IN_PROGRESS", "PENDING"}:
                inc["recovery"] = "RECOVERED"
            _event(state, "INCIDENT_RESOLVED", now, key=key, resolution=inc["resolution"])
            record_experience(data_dir, inc, outcome=inc["resolution"])
            if inc.get("alerted_at") and email:
                sender = sender if sender is not None else sender_factory()
                if sender is not None:
                    subject, body = build_resolved(inc, day=day)
                    if _send(sender, subject, body):
                        inc["resolved_mail_at"] = clock.isoformat()
            continue

        inc["missing_ticks"] = int(inc.get("missing_ticks") or 0) + 1
        if inc["missing_ticks"] <= RESOLVED_GRACE_TICKS:
            continue

        # F&O paper-worker outages must not become "condition cleared" merely because
        # the market window ended. Require a pack write or an explicit verified recovery.
        if key == "fno:paper_worker":
            inc["status"] = STATUS_UNRESOLVED
            inc["resolved_at"] = clock.isoformat()
            inc["resolution"] = "market_window_ended_without_recovery"
            _event(
                state,
                "INCIDENT_UNRESOLVED",
                now,
                key=key,
                resolution=inc["resolution"],
            )
            record_experience(data_dir, inc, outcome=inc["resolution"])
            continue

        inc["status"] = STATUS_RESOLVED
        inc["resolved_at"] = clock.isoformat()
        auto = inc.get("recovery") in {"RECOVERED_PENDING_CONFIRM", "IN_PROGRESS", "EXHAUSTED"}
        inc["resolution"] = "automatic recovery confirmed" if inc.get("recovery") == "RECOVERED_PENDING_CONFIRM" else (
            "cleared after recovery attempts" if auto else "condition cleared"
        )
        if inc.get("recovery") == "RECOVERED_PENDING_CONFIRM":
            inc["recovery"] = "RECOVERED"
        _event(state, "INCIDENT_RESOLVED", now, key=key, resolution=inc["resolution"])
        record_experience(data_dir, inc, outcome=inc["resolution"])
        if inc.get("alerted_at") and email:
            sender = sender if sender is not None else sender_factory()
            if sender is not None:
                subject, body = build_resolved(inc, day=day)
                if _send(sender, subject, body):
                    inc["resolved_mail_at"] = clock.isoformat()

    state["updated_at"] = clock.isoformat()
    state["fno"] = fno["summary"]
    _closed = {STATUS_RESOLVED, STATUS_RECOVERED_VERIFIED}
    state["open_incidents"] = sorted(
        k for k, v in incidents.items() if v.get("status") not in _closed
    )
    state["heartbeat_at"] = clock.isoformat()
    _write_json(state_path(data_dir, day), state)
    _write_json(_root(data_dir) / "heartbeat.json", {"at": clock.isoformat(), "ist_day": day, "version": VERSION})
    return {
        "ok": True,
        "fno_category": cat,
        "open_incidents": state["open_incidents"],
        "alerts_sent": len(state["alerts"]),
        "fno_readiness": (state.get("fno_readiness") or {}).get("readiness"),
    }


def _last_systemic_alert(data_dir: Path, key: str, day: str) -> str | None:
    d = date.fromisoformat(day)
    for back in range(1, SYSTEMIC_REALERT_DAYS):
        prior = (d - timedelta(days=back)).isoformat()
        doc = _read_json(state_path(data_dir, prior))
        hit = (doc.get("systemic_alerted") or {}).get(key)
        if hit:
            return str(hit)
    return None


# --- P2 digest + silent-window audit ---------------------------------------------------


def digest_lines(data_dir: str | Path, day: str) -> list[str]:
    """Evening-digest section: every incident of the day (P2 lives only here)."""
    state = load_state(data_dir, day)
    incidents = state.get("incidents") or {}
    window = (state.get("windows") or {}).get(FNO_LAB) or {}
    lines = ["OPERATIONAL HEALTH (Loop 0)"]
    minutes = window.get("minutes") or {}
    if minutes:
        lines.append(
            "  F&O window minutes by state: "
            + ", ".join(f"{k}={int(v)}" for k, v in sorted(minutes.items()))
        )
    if not incidents:
        lines.append("  No operational incidents recorded today.")
    for key, inc in sorted(incidents.items(), key=lambda kv: str(kv[1].get("opened_at"))):
        lines.append(
            f"  [{inc.get('severity')}] {inc.get('what')} — {inc.get('status')}"
            f" (opened {_ist_hm(inc.get('opened_at'))}"
            + (f", resolved {_ist_hm(inc.get('resolved_at'))}" if inc.get("resolved_at") else "")
            + f"; recovery {inc.get('recovery')}"
            + ("; alerted" if inc.get("alerted_at") else "")
            + ")"
        )
    silent = silent_degraded_windows(data_dir, day)
    if silent:
        lines.append(f"  ACCEPTANCE VIOLATION: {len(silent)} degraded incident(s) without recovery or alert: {', '.join(silent)}")
    return lines


def silent_degraded_windows(data_dir: str | Path, day: str) -> list[str]:
    """Incidents that persisted past the P1 window with neither recovery nor an alert."""
    state = load_state(data_dir, day)
    out = []
    for key, inc in (state.get("incidents") or {}).items():
        if inc.get("category") not in {IDLE_INFRA, IDLE_WORKER, IDLE_CAPABILITY}:
            continue
        opened = _parse_ts(inc.get("opened_at"))
        end = _parse_ts(inc.get("resolved_at") or inc.get("last_seen"))
        if not opened or not end or (end - opened).total_seconds() < P1_PERSIST_S:
            continue
        recovered = inc.get("recovery") == "RECOVERED"
        alerted = bool(inc.get("alerted_at") or inc.get("alert_owner"))
        if not (recovered or alerted or inc.get("category") == IDLE_CAPABILITY):
            out.append(key)
    return out
