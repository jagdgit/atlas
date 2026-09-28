"""OI-CHAT-INFER0 — CPU-slow / no-GPU inference policy.

Atlas runs Ollama on CPU without a GPU. Generate times of 40–90s+ for short
chat are expected. This module is the single place that encodes that reality:

- Prefer deterministic answers (glossary, self-model, status) over Ollama.
- Keep max_concurrency=1 until Stage 7 fitness proves otherwise.
- Bound chat context so Living RAG does not push interactive turns over budget.
- Stage 7 hardware advice is advisory only — never auto-raise concurrency.
"""

from __future__ import annotations

from typing import Any

VERSION = "chat_infer0.cpu_policy.v1"

# Live measured envelope on this host (2026-08-20): short joke ~43–52s generate.
DEFAULT_INTERACTIVE_TIMEOUT_S = 120.0
DEFAULT_CHAT_MAX_CONTEXT_CHARS = 2400
# DP-LLM1 LOCK 2026-08-24 — operator raised from 1; RTH reserves live slots.
DEFAULT_MAX_CONCURRENCY = 2


def accelerator_from_config(cfg: Any | None = None) -> str:
    """Return 'cpu' | 'gpu' — defaults to cpu (no GPU on operator hardware)."""
    if cfg is None:
        try:
            from atlas.config import get_config

            cfg = get_config()
        except Exception:  # noqa: BLE001
            return "cpu"
    llm = getattr(cfg, "llm", None)
    acc = getattr(llm, "accelerator", None) if llm is not None else None
    if acc:
        return str(acc).strip().lower() or "cpu"
    return "cpu"


def is_cpu_slow(cfg: Any | None = None) -> bool:
    return accelerator_from_config(cfg) == "cpu"


def interactive_timeout_s(cfg: Any | None = None) -> float:
    if cfg is None:
        try:
            from atlas.config import get_config

            cfg = get_config()
        except Exception:  # noqa: BLE001
            return DEFAULT_INTERACTIVE_TIMEOUT_S
    llm = getattr(cfg, "llm", None)
    if llm is not None and getattr(llm, "interactive_timeout", None) is not None:
        try:
            return float(llm.interactive_timeout)
        except (TypeError, ValueError):
            pass
    return DEFAULT_INTERACTIVE_TIMEOUT_S


def chat_max_context_chars(cfg: Any | None = None) -> int:
    if cfg is None:
        try:
            from atlas.config import get_config

            cfg = get_config()
        except Exception:  # noqa: BLE001
            return DEFAULT_CHAT_MAX_CONTEXT_CHARS
    llm = getattr(cfg, "llm", None)
    raw = getattr(llm, "chat_max_context_chars", None) if llm is not None else None
    if raw is not None:
        try:
            return max(400, int(raw))
        except (TypeError, ValueError):
            pass
    return DEFAULT_CHAT_MAX_CONTEXT_CHARS


def truncate_text(text: str, *, max_chars: int | None = None) -> str:
    limit = max_chars if max_chars is not None else DEFAULT_CHAT_MAX_CONTEXT_CHARS
    t = text or ""
    if len(t) <= limit:
        return t
    return t[: max(0, limit - 20)].rstrip() + "\n…[truncated for CPU]"


def truncate_chat_messages(
    messages: list[Any],
    *,
    max_chars: int | None = None,
) -> list[Any]:
    """Bound total user/system content for CPU interactive turns (keep last user)."""
    limit = max_chars if max_chars is not None else DEFAULT_CHAT_MAX_CONTEXT_CHARS
    if not messages or limit <= 0:
        return messages
    # Soft budget across non-final messages; never empty the last user turn.
    budget = limit
    out: list[Any] = []
    last_i = len(messages) - 1
    for i, m in enumerate(messages):
        content = getattr(m, "content", None)
        if content is None and isinstance(m, dict):
            content = m.get("content")
        content = str(content or "")
        if i == last_i:
            out.append(m)
            continue
        if len(content) > budget // 2 and budget > 200:
            content = truncate_text(content, max_chars=max(200, budget // 2))
            if hasattr(m, "content"):
                try:
                    from atlas.llm.provider import ChatMessage

                    m = ChatMessage(getattr(m, "role", "user"), content)
                except Exception:  # noqa: BLE001
                    pass
            elif isinstance(m, dict):
                m = {**m, "content": content}
        budget = max(0, budget - len(content))
        out.append(m)
    return out


def hardware_limit_advice(
    fitness_summary: dict[str, Any] | None,
    *,
    interactive_timeout: float | None = None,
    accelerator: str = "cpu",
    max_concurrency: int = 1,
) -> dict[str, Any]:
    """Stage 7 — advisory only. Never mutates concurrency or pulls models."""
    summary = fitness_summary if isinstance(fitness_summary, dict) else {}
    outcomes = summary.get("outcomes") if isinstance(summary.get("outcomes"), dict) else {}
    n = int(summary.get("inferences") or 0)
    ok = int(outcomes.get("ok") or 0)
    timeout = int(outcomes.get("timeout") or 0) + int(outcomes.get("error") or 0)
    busy = int(outcomes.get("busy") or 0) + int(outcomes.get("lane_busy") or 0)
    by_lane = summary.get("by_lane") if isinstance(summary.get("by_lane"), dict) else {}
    chat = by_lane.get("chat") if isinstance(by_lane.get("chat"), dict) else {}
    gen_p95 = chat.get("generate_p95_ms")
    wait_p95 = chat.get("queue_wait_p95_ms")
    timeout_s = float(
        interactive_timeout
        if interactive_timeout is not None
        else DEFAULT_INTERACTIVE_TIMEOUT_S
    )
    timeout_ms = timeout_s * 1000.0

    recommend_gpu = False
    recommend_concurrency_bump = False
    reasons: list[str] = []

    if accelerator == "cpu":
        reasons.append(
            "Host is CPU-only (no GPU) — 40–90s+ generate for short chat is expected."
        )

    if n >= 5 and timeout >= 2 and gen_p95 is not None and float(gen_p95) >= 0.85 * timeout_ms:
        recommend_gpu = True
        reasons.append(
            f"Chat generate_p95={gen_p95}ms approaches interactive_timeout={timeout_s}s "
            "with repeated timeouts — GPU or smaller prompts would help."
        )

    if wait_p95 is not None and float(wait_p95) > 5_000 and busy >= 2:
        reasons.append(
            f"queue_wait_p95={wait_p95}ms with busy hits — scheduling/contention, "
            "not first reason to buy GPU."
        )

    # Explicit lock: concurrency bump is last, never first, and not auto-applied.
    if (
        n >= 20
        and wait_p95 is not None
        and float(wait_p95) > 15_000
        and ok >= 10
        and timeout == 0
        and max_concurrency <= 1
    ):
        recommend_concurrency_bump = True
        reasons.append(
            "Sustained queue wait with healthy generates — *consider* concurrency=2 "
            "only after operator LOCK (Stage 7 experiment B). Not applied automatically."
        )

    return {
        "version": VERSION,
        "accelerator": accelerator,
        "max_concurrency": max_concurrency,
        "recommend_gpu": recommend_gpu,
        "recommend_concurrency_bump": recommend_concurrency_bump,
        "auto_applied": False,
        "sample_inferences": n,
        "reasons": reasons,
        "honesty": (
            "Stage 7 advice only. Do not raise max_concurrency or model size as the "
            "first fix. Prefer deterministic routes + shorter context on CPU."
        ),
    }


def format_cpu_policy_evening_lines(
    fitness_summary: dict[str, Any] | None,
    *,
    interactive_timeout: float | None = None,
    accelerator: str | None = None,
    max_concurrency: int = 1,
) -> list[str]:
    acc = accelerator or "cpu"
    advice = hardware_limit_advice(
        fitness_summary,
        interactive_timeout=interactive_timeout,
        accelerator=acc,
        max_concurrency=max_concurrency,
    )
    lines = [
        "",
        "── CPU / hardware gate (OI-CHAT-INFER0 Stage 7) ──",
        f"  accelerator={advice.get('accelerator')} · "
        f"max_concurrency={advice.get('max_concurrency')} (locked unless operator LOCK) · "
        f"auto_applied={advice.get('auto_applied')}",
        f"  recommend_gpu={advice.get('recommend_gpu')} · "
        f"recommend_concurrency_bump={advice.get('recommend_concurrency_bump')}",
    ]
    for r in list(advice.get("reasons") or [])[:4]:
        lines.append(f"  · {r}")
    lines.append(str(advice.get("honesty") or ""))
    return lines
