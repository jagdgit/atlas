"""OI-CHAT-INFER0 Stage 0 — LLM fitness / utilization ledger.

Observability is the measurement foundation for progressively increasing Atlas's
effective use of local LLM reasoning and for determining, from workload quality,
latency and (later) cognitive ROI, when hardware/model is the limiting factor.

Not: use Ollama as much as possible.
Yes: measure every inference; spend compute where reasoning creates learning value.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

VERSION = "chat_infer0.fitness.v1"
STORE_REL = Path("investment") / "llm_fitness"
_IST = ZoneInfo("Asia/Kolkata")
_log = logging.getLogger("atlas.llm.fitness_ledger")


def ist_today() -> str:
    return datetime.now(_IST).strftime("%Y-%m-%d")


def day_path(data_dir: str | Path | None, as_of_ist: str | None = None) -> Path | None:
    if not data_dir:
        return None
    return Path(data_dir) / STORE_REL / f"{as_of_ist or ist_today()}.jsonl"


def _data_dir() -> str | None:
    try:
        from atlas.config import get_config

        return str(get_config().paths.data)
    except Exception:  # noqa: BLE001
        return None


def _host_snapshot() -> dict[str, Any]:
    out: dict[str, Any] = {}
    try:
        load1, load5, load15 = os.getloadavg()
        out["load1"] = round(float(load1), 2)
        out["load5"] = round(float(load5), 2)
        out["load15"] = round(float(load15), 2)
    except OSError:
        pass
    try:
        # Linux: MemAvailable from /proc/meminfo
        avail = total = None
        with open("/proc/meminfo", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("MemAvailable:"):
                    avail = int(line.split()[1])  # kB
                elif line.startswith("MemTotal:"):
                    total = int(line.split()[1])
        if avail is not None:
            out["mem_available_mb"] = round(avail / 1024.0, 1)
        if total is not None:
            out["mem_total_mb"] = round(total / 1024.0, 1)
    except OSError:
        pass
    return out


def record_inference(
    data_dir: str | Path | None = None,
    *,
    lane: str,
    role: str,
    model: str | None = None,
    kind: str = "chat",  # chat | generate | embed | busy_preflight
    outcome: str = "ok",  # ok | error | timeout | busy | lane_busy
    queue_wait_ms: float | None = None,
    generate_ms: float | None = None,
    total_ms: float | None = None,
    prompt_tokens: int | None = None,
    context_tokens: int | None = None,
    output_tokens: int | None = None,
    tokens_per_sec: float | None = None,
    purpose: str | None = None,
    reason: str | None = None,
    error: str | None = None,
    usage: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Append one inference fitness row (fail-open)."""
    dd = data_dir if data_dir is not None else _data_dir()
    path = day_path(dd)
    now = datetime.now(timezone.utc)
    usage = usage if isinstance(usage, dict) else {}
    # Prefer explicit token fields; fall back to Ollama usage keys
    pt = prompt_tokens
    if pt is None:
        pt = usage.get("prompt_eval_count") or usage.get("prompt_tokens")
    ot = output_tokens
    if ot is None:
        ot = usage.get("eval_count") or usage.get("completion_tokens")
    gen = generate_ms
    if gen is None and usage.get("eval_duration_ms") is not None:
        try:
            gen = float(usage["eval_duration_ms"])
        except (TypeError, ValueError):
            gen = None
    if gen is None and usage.get("eval_duration") is not None:
        try:
            # Ollama reports nanoseconds
            gen = float(usage["eval_duration"]) / 1_000_000.0
        except (TypeError, ValueError):
            gen = None
    if tokens_per_sec is None and ot is not None and gen and gen > 0:
        try:
            tokens_per_sec = round(float(ot) / (float(gen) / 1000.0), 2)
        except (TypeError, ValueError):
            tokens_per_sec = None
    qw = queue_wait_ms
    tot = total_ms
    if tot is None and qw is not None and gen is not None:
        tot = float(qw) + float(gen)
    row: dict[str, Any] = {
        "version": VERSION,
        "kind": "LLM_FITNESS",
        "inference_id": str(uuid4()),
        "recorded_at": now.isoformat(),
        "as_of_ist": ist_today(),
        "lane": str(lane or "background"),
        "role": str(role or "unknown"),
        "model": model,
        "call_kind": kind,
        "outcome": outcome,
        "queue_wait_ms": round(float(qw), 1) if qw is not None else None,
        "generate_ms": round(float(gen), 1) if gen is not None else None,
        "total_ms": round(float(tot), 1) if tot is not None else None,
        "prompt_tokens": int(pt) if pt is not None else None,
        "context_tokens": context_tokens,
        "output_tokens": int(ot) if ot is not None else None,
        "tokens_per_sec": tokens_per_sec,
        "purpose": (purpose or "")[:200] or None,
        "reason": (reason or "")[:200] or None,
        "error": (error or "")[:300] or None,
        "host": _host_snapshot(),
        "honesty": (
            "Fitness ledger — measure first. Not a mandate to maximize Ollama use. "
            "Cognitive ROI fields (decision_impact) come later."
        ),
    }
    if extra:
        row["extra"] = {k: v for k, v in extra.items() if v is not None}
    if path is None:
        return {"ok": False, "reason": "no_data_dir", "row": row}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, default=str) + "\n")
        return {"ok": True, "path": str(path), "inference_id": row["inference_id"]}
    except OSError as exc:
        _log.debug("fitness ledger write failed", exc_info=True)
        return {"ok": False, "reason": type(exc).__name__}


def load_day(
    data_dir: str | Path | None,
    *,
    as_of_ist: str | None = None,
    limit: int = 5000,
) -> list[dict[str, Any]]:
    path = day_path(data_dir, as_of_ist)
    if path is None or not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                out.append(row)
            if len(out) >= max(1, int(limit)):
                break
    except OSError:
        return []
    return out


def _percentile(sorted_vals: list[float], p: float) -> float | None:
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    idx = min(len(sorted_vals) - 1, max(0, int(round((p / 100.0) * (len(sorted_vals) - 1)))))
    return sorted_vals[idx]


def summarize_day(rows: list[dict[str, Any]] | None) -> dict[str, Any]:
    data = [r for r in (rows or []) if isinstance(r, dict)]
    by_lane: dict[str, list[dict[str, Any]]] = {}
    outcomes: dict[str, int] = {}
    for r in data:
        lane = str(r.get("lane") or "unknown")
        by_lane.setdefault(lane, []).append(r)
        oc = str(r.get("outcome") or "unknown")
        outcomes[oc] = int(outcomes.get(oc) or 0) + 1

    def _lane_stats(items: list[dict[str, Any]]) -> dict[str, Any]:
        gens = sorted(
            float(x["generate_ms"])
            for x in items
            if x.get("generate_ms") is not None
        )
        waits = sorted(
            float(x["queue_wait_ms"])
            for x in items
            if x.get("queue_wait_ms") is not None
        )
        n = len(items)
        timeouts = sum(1 for x in items if x.get("outcome") in {"timeout", "error"})
        busy = sum(1 for x in items if x.get("outcome") in {"busy", "lane_busy"})
        oks = sum(1 for x in items if x.get("outcome") == "ok")
        return {
            "n": n,
            "ok": oks,
            "busy": busy,
            "timeout_or_error": timeouts,
            "timeout_rate": round(timeouts / n, 3) if n else 0.0,
            "generate_p50_ms": _percentile(gens, 50),
            "generate_p95_ms": _percentile(gens, 95),
            "queue_wait_p50_ms": _percentile(waits, 50),
            "queue_wait_p95_ms": _percentile(waits, 95),
        }

    lanes = {k: _lane_stats(v) for k, v in by_lane.items()}
    return {
        "version": VERSION,
        "inferences": len(data),
        "outcomes": outcomes,
        "by_lane": lanes,
        "honesty": (
            "Stage 0 fitness — p50/p95 are generate_ms when present. "
            "Cognitive ROI (decision impact) not yet scored."
        ),
    }


def format_fitness_evening_lines(
    data_dir: str | Path | None,
    *,
    as_of_ist: str | None = None,
) -> list[str]:
    rows = load_day(data_dir, as_of_ist=as_of_ist)
    summary = summarize_day(rows)
    lines = [
        "",
        "── LLM fitness (OI-CHAT-INFER0 Stages 0–1) ──",
        f"  inferences today: {summary.get('inferences', 0)} · "
        f"outcomes={summary.get('outcomes') or {}}",
    ]
    by_lane = summary.get("by_lane") if isinstance(summary.get("by_lane"), dict) else {}
    if not by_lane:
        lines.append("  (no inference samples yet — chat/market/research will populate)")
    else:
        for lane, st in sorted(by_lane.items()):
            if not isinstance(st, dict):
                continue
            lines.append(
                f"  · {lane}: n={st.get('n')} ok={st.get('ok')} "
                f"busy={st.get('busy')} err/timeout={st.get('timeout_or_error')} "
                f"gen_p50={st.get('generate_p50_ms')}ms "
                f"gen_p95={st.get('generate_p95_ms')}ms "
                f"wait_p95={st.get('queue_wait_p95_ms')}ms"
            )
    lines.append(str(summary.get("honesty") or ""))
    return lines


def timed_ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000.0, 1)
