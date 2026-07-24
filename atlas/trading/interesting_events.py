"""Interesting-event scoring for Market Intelligence (MI.4 / Q5).

Scores are in ``[0, 1]``. Opt-in research spawn uses ``score >= threshold``.
Not only price moves — volume spikes and operator-tagged catalysts also score.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class InterestingEvent:
    symbol: str
    kind: str  # price_move | volume_spike | catalyst | composite
    score: float
    detail: str
    pct_move: float | None = None
    volume_ratio: float | None = None
    provider: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def research_objective(self) -> str:
        """Objective string for JobService.create_job (research_first path)."""
        bits = [f"Why did {self.symbol} move?"]
        if self.pct_move is not None:
            bits.append(f"Observed {self.pct_move:+.2f}% move.")
        bits.append(f"Event kind={self.kind}; score={self.score:.2f}.")
        bits.append(self.detail)
        bits.append("Gather recent news and filings; extract claims; verify.")
        return " ".join(bits)


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def score_price_move(
    symbol: str,
    pct_move: float | None,
    *,
    alert_pct: float = 5.0,
    provider: str | None = None,
) -> InterestingEvent | None:
    """Score absolute percent move relative to alert threshold."""
    if pct_move is None:
        return None
    try:
        move = float(pct_move)
    except (TypeError, ValueError):
        return None
    threshold = max(float(alert_pct), 1e-6)
    abs_move = abs(move)
    if abs_move < threshold:
        return None
    # 1× threshold → 0.5; 4× → 1.0
    score = _clamp01(0.5 + (abs_move / threshold - 1.0) / 6.0)
    return InterestingEvent(
        symbol=symbol,
        kind="price_move",
        score=score,
        detail=f"{symbol} moved {move:+.2f}% (alert {threshold:g}%)",
        pct_move=move,
        provider=provider,
    )


def score_volume_spike(
    symbol: str,
    volume_ratio: float | None,
    *,
    min_ratio: float = 2.5,
    provider: str | None = None,
) -> InterestingEvent | None:
    """Score volume vs recent average (ratio ≥ min_ratio)."""
    if volume_ratio is None:
        return None
    try:
        ratio = float(volume_ratio)
    except (TypeError, ValueError):
        return None
    if ratio < min_ratio:
        return None
    score = _clamp01(0.45 + (ratio - min_ratio) / 10.0)
    return InterestingEvent(
        symbol=symbol,
        kind="volume_spike",
        score=score,
        detail=f"{symbol} volume {ratio:.1f}× recent average",
        volume_ratio=ratio,
        provider=provider,
    )


def score_catalyst(
    symbol: str,
    *,
    kind: str,
    detail: str,
    base_score: float = 0.75,
) -> InterestingEvent:
    """Operator/news-tagged catalyst (earnings, CEO, circuit, …)."""
    return InterestingEvent(
        symbol=symbol,
        kind=kind or "catalyst",
        score=_clamp01(base_score),
        detail=detail or kind,
        metadata={"catalyst": True},
    )


def volume_ratio_from_bars(bars: list[dict[str, Any]], *, lookback: int = 20) -> float | None:
    """Last bar volume / mean of prior lookback volumes."""
    if not bars or len(bars) < 3:
        return None
    try:
        vols = [float(b.get("volume") or 0.0) for b in bars]
    except (TypeError, ValueError):
        return None
    last = vols[-1]
    prior = [v for v in vols[-(lookback + 1) : -1] if v > 0]
    if not prior or last <= 0:
        return None
    avg = sum(prior) / len(prior)
    if avg <= 0:
        return None
    return last / avg


def merge_events(events: list[InterestingEvent]) -> InterestingEvent | None:
    """Combine same-symbol events into one composite with max score."""
    if not events:
        return None
    if len(events) == 1:
        return events[0]
    best = max(events, key=lambda e: e.score)
    kinds = sorted({e.kind for e in events})
    detail = "; ".join(e.detail for e in events)
    return InterestingEvent(
        symbol=best.symbol,
        kind="composite" if len(kinds) > 1 else best.kind,
        score=_clamp01(min(1.0, best.score + 0.05 * (len(events) - 1))),
        detail=detail,
        pct_move=best.pct_move,
        volume_ratio=best.volume_ratio,
        provider=best.provider,
        metadata={"kinds": kinds},
    )


def score_observation(
    symbol: str,
    *,
    pct_move: float | None = None,
    bars: list[dict[str, Any]] | None = None,
    alert_pct: float = 5.0,
    volume_min_ratio: float = 2.5,
    provider: str | None = None,
) -> InterestingEvent | None:
    """Score one symbol observation from move + optional volume."""
    parts: list[InterestingEvent] = []
    price = score_price_move(
        symbol, pct_move, alert_pct=alert_pct, provider=provider
    )
    if price is not None:
        parts.append(price)
    if bars:
        ratio = volume_ratio_from_bars(bars)
        vol = score_volume_spike(
            symbol, ratio, min_ratio=volume_min_ratio, provider=provider
        )
        if vol is not None:
            parts.append(vol)
    return merge_events(parts)
