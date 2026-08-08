"""LQ.7 — Yahoo slow-and-steady rate gate (hermetic)."""

from __future__ import annotations

from atlas.investment.yahoo_fundamentals import (
    YahooRateGate,
    is_yahoo_rate_block_error,
    reset_yahoo_rate_gate_for_tests,
)


def test_rate_gate_backoff_and_persist(tmp_path):
    reset_yahoo_rate_gate_for_tests()
    gate = YahooRateGate(
        data_dir=tmp_path,
        min_interval_s=0.01,
        backoff_start_s=30.0,
        backoff_max_s=120.0,
        backoff_mult=2.0,
    )
    assert gate.remaining_cooldown_s() == 0
    cool = gate.on_block(429)
    assert cool == 30.0
    assert gate.remaining_cooldown_s() > 25
    st = gate.status()
    assert st["ready"] is False
    assert st["last_block_status"] == 429
    assert (tmp_path / "investment" / "fundamentals" / "yahoo_rate_gate.json").is_file()

    # Reload from disk
    gate2 = YahooRateGate(data_dir=tmp_path, backoff_start_s=30.0)
    assert gate2.remaining_cooldown_s() > 20
    assert gate2._consecutive_blocks >= 1

    gate2.on_success()
    # success clears consecutive but cooldown already set — wait: on_success clears cooldown
    assert gate2.remaining_cooldown_s() == 0


def test_rate_gate_401_shorter_first_pause(tmp_path):
    gate = YahooRateGate(
        data_dir=tmp_path,
        backoff_start_s=90.0,
        backoff_max_s=900.0,
    )
    cool = gate.on_block(401)
    assert cool == 45.0
    cool2 = gate.on_block(401)
    assert cool2 == 90.0  # ladder after first


def test_is_yahoo_rate_block_error():
    assert is_yahoo_rate_block_error("HTTP 429 from Yahoo quoteSummary")
    assert is_yahoo_rate_block_error("HTTP 401 from Yahoo getcrumb")
    assert not is_yahoo_rate_block_error("empty_quote_summary")
