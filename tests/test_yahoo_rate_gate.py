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


def test_wait_interval_only_skips_crumb_cooldown(tmp_path):
    gate = YahooRateGate(
        data_dir=tmp_path,
        min_interval_s=0.0,
        backoff_start_s=600.0,
        backoff_max_s=900.0,
    )
    gate.on_block(429)
    assert gate.remaining_cooldown_s() > 100
    waited = gate.wait(respect_cooldown=False)
    assert waited < 1.0
    assert gate.remaining_cooldown_s() > 100


def test_parse_quote_html_pe_patterns():
    from atlas.investment.yahoo_fundamentals import parse_quote_html

    html = (
        'x"trailingPE":{"raw":33.79},"priceToBook":{"raw":3.3},'
        '"returnOnEquity":{"raw":0.104},"debtToEquity":{"raw":12.5},'
        'fin-streamer data-field="regularMarketPrice" value="1463.8"'
    )
    fields = parse_quote_html(html, symbol="CIPLA.NS")["fields"]
    assert fields.get("pe") == 33.79
    assert fields.get("roe") == 10.4
    assert fields.get("debt_to_equity") == 12.5


def test_obtain_crumb_429_notes_once(monkeypatch, tmp_path):
    """One getcrumb 429 must arm cooldown once (no double on_block)."""
    reset_yahoo_rate_gate_for_tests()
    from atlas.investment.yahoo_fundamentals import YahooFundamentalsProvider

    gate = YahooRateGate(
        data_dir=tmp_path,
        min_interval_s=0.0,
        backoff_start_s=60.0,
        backoff_max_s=900.0,
    )
    notes: list[int] = []
    orig = gate.on_block

    def _wrap(code):
        notes.append(int(code or 0))
        return orig(code)

    monkeypatch.setattr(gate, "on_block", _wrap)

    class _Resp:
        def __init__(self, status_code: int, text: str = ""):
            self.status_code = status_code
            self.text = text

    class _Client:
        def get(self, url):
            if "crumb" in str(url):
                return _Resp(429)
            return _Resp(200)

    prov = YahooFundamentalsProvider(
        enabled=True, data_dir=tmp_path, rate_gate=gate, opener=None
    )
    prov._client = _Client()  # noqa: SLF001
    try:
        prov._obtain_crumb(prov._client, force=True)  # noqa: SLF001
        raise AssertionError("expected RuntimeError")
    except RuntimeError as exc:
        assert "429" in str(exc)
    assert notes == [429]
    assert gate._consecutive_blocks == 1
    assert gate.remaining_cooldown_s() > 50
