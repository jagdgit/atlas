#!/usr/bin/env python3
"""Loop 0 external watchdog — alerts when Atlas cannot alert for itself.

Run by ``atlas-ops-watchdog.timer`` every 5 minutes, outside the Atlas process. Checks:

* ``atlas.service`` is active (P0 when not);
* the Loop 0 heartbeat (``investment/ops_health/heartbeat.json``, written every provider-health
  tick, ~120 s) is younger than 10 minutes (P0 when stale: scheduler stopped or wedged);
* PostgreSQL accepts TCP connections on the configured host/port (P0 when not);
* OI-OPS-1INST L6: exactly one ``atlas serve``; L1 lock pid == systemd MainPID;
  no recent ``Errno 98`` / address-already-in-use in the journal; L1 override → P1.

One email per failure, a reminder every 60 minutes while it persists, and a RESOLVED mail when
it clears. Never touches orders, Atlas state, or the service itself. Always exits 0.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

IST = ZoneInfo("Asia/Kolkata")
HEARTBEAT_MAX_AGE_S = 10 * 60
REMIND_EVERY_S = 60 * 60
SUBJECT_PREFIX = "[Atlas OPS]"
ERRNO98_LOOKBACK = "15 min"

WHAT_TO_DO = {
    "service_down": [
        "Check `systemctl status atlas` and `journalctl -u atlas -n 200`.",
        "Restart with `sudo systemctl restart atlas` once the cause is clear.",
    ],
    "heartbeat_stale": [
        "The process is up but the scheduler is not completing ticks.",
        "Check `journalctl -u atlas -n 200` for a hung task; restart atlas if it does not recover.",
    ],
    "db_down": [
        "Check `systemctl status postgresql` and disk space on the database volume.",
    ],
    "multi_instance": [
        "Exactly one `atlas serve` must run. `systemctl status atlas` and `ps -ef | grep atlas`.",
        "Stop hand-started copies; never `kill -9` the systemd MainPID without a plan.",
        "After 15:45 IST, `sudo systemctl restart atlas` once ownership is clear.",
    ],
    "lock_pid_mismatch": [
        "L1 lock holder pid must equal systemd MainPID.",
        "Inspect `/data/atlas_data/run/atlas.lock` and `systemctl show atlas -p MainPID`.",
    ],
    "errno98_recent": [
        "Address-already-in-use means a duplicate tried to bind :8000.",
        "Confirm a single instance; review journal for crash-loop copies.",
    ],
    "instance_lock_override": [
        "ATLAS_INSTANCE_LOCK_OVERRIDE is set — L1 is disabled (P1).",
        "Confirm no other instance, then remove the override from /etc/atlas/atlas.env.",
    ],
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _service_active() -> tuple[bool, str]:
    try:
        out = subprocess.run(
            ["systemctl", "is-active", "atlas"], capture_output=True, text=True, timeout=20
        )
        state = (out.stdout or out.stderr).strip() or "unknown"
        return state == "active", state
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


def _heartbeat_age(data_dir: Path) -> float | None:
    path = data_dir / "investment" / "ops_health" / "heartbeat.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        at = datetime.fromisoformat(str(doc["at"]))
    except Exception:  # noqa: BLE001
        return None
    return (_now() - at).total_seconds()


def _db_reachable(host: str, port: int) -> tuple[bool, str]:
    try:
        with socket.create_connection((host, port), timeout=5):
            return True, f"{host}:{port} accepting connections"
    except OSError as exc:
        return False, f"{host}:{port} {type(exc).__name__}: {exc}"


def _main_pid() -> int | None:
    try:
        out = subprocess.run(
            ["systemctl", "show", "atlas", "-p", "MainPID", "--value"],
            capture_output=True,
            text=True,
            timeout=20,
        )
        raw = (out.stdout or "").strip()
        pid = int(raw)
        return pid if pid > 0 else None
    except Exception:  # noqa: BLE001
        return None


def _atlas_serve_pids() -> list[int]:
    """PIDs whose argv is the real ``atlas serve`` CLI (not IDE sandboxes).

    Requires a token ``serve`` immediately after an ``atlas`` entrypoint
    (``atlas``, ``…/bin/atlas``, or ``python …/atlas``). Excludes Cursor
    sandbox shells that merely *mention* those strings in a script body.
    """
    pids: list[int] = []
    noise = (
        "cursorsandbox",
        "cursor/resources",
        "ops_watchdog",
        "sandbox-policy",
    )
    try:
        out = subprocess.run(
            ["ps", "-eo", "pid=,args="],
            capture_output=True,
            text=True,
            timeout=20,
        )
    except Exception:  # noqa: BLE001
        return pids
    for line in (out.stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            pid_s, args = line.split(None, 1)
        except ValueError:
            continue
        if any(n in args for n in noise):
            continue
        parts = args.split()
        try:
            serve_i = parts.index("serve")
        except ValueError:
            continue
        if serve_i < 1:
            continue
        prev = parts[serve_i - 1]
        # Real CLI only:
        #   /data/atlas/.venv/bin/atlas serve
        #   python3 /data/atlas/.venv/bin/atlas serve
        #   atlas serve   (argv0 == atlas, serve is argv1)
        # Not: bash -c '… atlas serve …' where "atlas" is mid-script.
        path_entry = prev.endswith("/atlas") or prev.endswith("/bin/atlas")
        bare_cli = prev == "atlas" and serve_i == 1
        if not (path_entry or bare_cli):
            continue
        try:
            pids.append(int(pid_s))
        except ValueError:
            pass
    seen: set[int] = set()
    uniq: list[int] = []
    for p in pids:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return uniq


def _lock_holder_pid(data_dir: Path) -> int | None:
    path = data_dir / "run" / "atlas.lock"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        pid = int(doc.get("pid"))
        return pid if pid > 0 else None
    except Exception:  # noqa: BLE001
        return None


def _errno98_recent() -> bool:
    try:
        out = subprocess.run(
            [
                "journalctl",
                "-u",
                "atlas",
                "--since",
                ERRNO98_LOOKBACK,
                "--no-pager",
                "-o",
                "cat",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        text = out.stdout or ""
        return (
            "address already in use" in text.lower()
            or "errno 98" in text.lower()
            or "[errno 98]" in text.lower()
        )
    except Exception:  # noqa: BLE001
        return False


def _override_active() -> bool:
    try:
        from atlas.ops.instance_lock import OVERRIDE_ENV, OVERRIDE_VALUE

        return os.environ.get(OVERRIDE_ENV) == OVERRIDE_VALUE
    except Exception:  # noqa: BLE001
        return (
            os.environ.get("ATLAS_INSTANCE_LOCK_OVERRIDE")
            == "I_CONFIRM_SINGLE_INSTANCE"
        )


def _checks(data_dir: Path, db_host: str, db_port: int) -> dict[str, dict]:
    findings: dict[str, dict] = {}
    active, state = _service_active()
    if not active:
        findings["service_down"] = {
            "what": f"atlas.service = {state}",
            "why": "The Atlas process is not running under systemd.",
            "impact": "No trading, learning, or Loop 0 health checks are running.",
            "severity": "P0",
        }
    age = _heartbeat_age(data_dir)
    if active and (age is None or age > HEARTBEAT_MAX_AGE_S):
        findings["heartbeat_stale"] = {
            "what": "Loop 0 heartbeat missing" if age is None else f"Loop 0 heartbeat {int(age // 60)} min old",
            "why": "The provider-health tick (every ~2 min) has stopped completing.",
            "impact": "Scheduled work is not running; Atlas cannot raise its own alerts.",
            "severity": "P0",
        }
    ok, detail = _db_reachable(db_host, db_port)
    if not ok:
        findings["db_down"] = {
            "what": "PostgreSQL unreachable",
            "why": detail,
            "impact": "Workers cannot read or write state; Atlas is effectively stopped.",
            "severity": "P0",
        }

    # --- OI-OPS-1INST L6 ---
    serve_pids = _atlas_serve_pids()
    if active and len(serve_pids) > 1:
        findings["multi_instance"] = {
            "what": f"{len(serve_pids)} atlas serve processes: {serve_pids}",
            "why": "More than one control plane is running (F17 class failure).",
            "impact": "Duplicate claims, mails, and recovery cycles are possible.",
            "severity": "P0",
        }
    main_pid = _main_pid() if active else None
    lock_pid = _lock_holder_pid(data_dir)
    if active and main_pid and lock_pid and lock_pid != main_pid:
        findings["lock_pid_mismatch"] = {
            "what": f"L1 lock pid={lock_pid} ≠ MainPID={main_pid}",
            "why": "The flock holder is not the systemd-managed process.",
            "impact": "A hand-started or stale instance may own side effects.",
            "severity": "P0",
        }
    if active and _errno98_recent():
        findings["errno98_recent"] = {
            "what": "Errno 98 / address already in use in last 15 min",
            "why": "A second process tried to bind the API port.",
            "impact": "Crash-loop copies may have started services before bind failed.",
            "severity": "P0",
        }
    if _override_active():
        findings["instance_lock_override"] = {
            "what": "ATLAS_INSTANCE_LOCK_OVERRIDE is set",
            "why": "L1 flock is intentionally disabled by the operator.",
            "impact": "Only L2/L3 prevent duplicates; override must be temporary.",
            "severity": "P1",
        }
    return findings


def _body(key: str, f: dict, *, day: str, opened: str, reminder: bool) -> str:
    severity = str(f.get("severity") or "P0")
    lines = [
        "ATLAS ACTION REQUIRED — PLATFORM" + (" (still failing)" if reminder else ""),
        f"Severity: {severity}",
        f"Day: {day}   Detected: {opened} IST   Category: E_WORKER_SCHEDULER_FAILURE",
        "",
        "WHAT FAILED",
        f"  {f['what']}",
        "",
        "WHY",
        f"  {f['why']}",
        "",
        "IMPACT",
        f"  {f['impact']}",
        "",
        "WHAT ATLAS TRIED",
        "  The external watchdog only observes; it does not restart the service.",
        "",
        "WHAT YOU CAN DO",
        *[f"  - {a}" for a in WHAT_TO_DO.get(key, [])],
        "",
        "Safety: No orders were submitted. Atlas places no orders while it is down.",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    try:
        from atlas.config import get_config

        cfg = get_config()
        data_dir = Path(cfg.paths.data)
        db_host, db_port = str(cfg.database.host), int(cfg.database.port)
    except Exception:  # noqa: BLE001
        data_dir, db_host, db_port = Path("/data/atlas_data"), "127.0.0.1", 5432

    state_path = data_dir / "investment" / "ops_health" / "watchdog.json"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        state = {}
    open_ = state.setdefault("open", {})

    findings = _checks(data_dir, db_host, db_port)
    now = _now()
    ist = now.astimezone(IST)
    day = ist.date().isoformat()

    sender = None
    try:
        from atlas.investment.zerodha_token_email import _email_sender

        sender = _email_sender()
    except Exception:  # noqa: BLE001
        sender = None

    def _send(subject: str, body: str) -> bool:
        if sender is None:
            return False
        try:
            return bool(sender.send(subject, body))
        except Exception:  # noqa: BLE001
            return False

    for key, f in findings.items():
        entry = open_.get(key)
        if entry is None:
            entry = {"opened_at": now.isoformat(), "opened_ist": ist.strftime("%H:%M"), "mails": 0}
            open_[key] = entry
        last = entry.get("last_mail_at")
        due = last is None or (now - datetime.fromisoformat(last)).total_seconds() >= REMIND_EVERY_S
        if due:
            sev = str(f.get("severity") or "P0")
            subject = (
                f"{SUBJECT_PREFIX} {sev} ACTION REQUIRED — PLATFORM: {f['what']} ({day})"
            )
            body = _body(key, f, day=day, opened=entry["opened_ist"], reminder=bool(last))
            if _send(subject, body):
                entry["last_mail_at"] = now.isoformat()
                entry["mails"] = int(entry.get("mails") or 0) + 1
            else:
                entry["mail_error"] = "email_not_configured" if sender is None else "smtp_failed"
        entry["last"] = f

    for key in [k for k in open_ if k not in findings]:
        entry = open_.pop(key)
        if entry.get("mails"):
            _send(
                f"{SUBJECT_PREFIX} RESOLVED — PLATFORM: {entry.get('last', {}).get('what')} ({day})",
                f"ATLAS RECOVERED — no action needed\nDay: {day}\n"
                f"Failure: {entry.get('last', {}).get('what')}\n"
                f"Opened: {entry.get('opened_ist')} IST   Resolved: {ist.strftime('%H:%M')} IST\n\n"
                "Safety: No orders were submitted.\n",
            )
        state.setdefault("history", []).append({**entry, "key": key, "resolved_at": now.isoformat()})
        state["history"] = state["history"][-50:]

    state["checked_at"] = now.isoformat()
    state["ok"] = not findings
    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass
    print(json.dumps({"ok": not findings, "open": sorted(open_)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
