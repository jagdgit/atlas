"""ReaderStrategyChain hermetic tests (Media Reader Family · M.2 / MD3)."""

from __future__ import annotations

from atlas.readers.strategy_chain import ReaderStrategyChain, StrategyResult
from atlas.transcripts.acquisition import REASON_NO_CAPTIONS, AcquisitionAttempt, AcquisitionRecord


def _to_acq(chain_result) -> AcquisitionRecord:
    attempts = [
        AcquisitionAttempt(
            strategy=r.name,
            outcome=r.outcome,
            reason=r.reason,
            reason_code=r.reason_code,
            bytes_read=r.bytes_read,
        )
        for r in chain_result.tried
    ]
    return AcquisitionRecord.from_attempts(
        attempts,
        source_url=chain_result.source_url,
        source_kind=chain_result.source_kind,
        suggested_next_capability=chain_result.suggested_next_capability,
    )


def test_chain_first_ok_wins_and_records_prior_failures():
    calls: list[str] = []

    def fail_a():
        calls.append("a")
        return StrategyResult("a", "skipped", reason="nope", reason_code=REASON_NO_CAPTIONS)

    def ok_b():
        calls.append("b")
        return StrategyResult("b", "ok", reason_code="ok", value={"text": "hi"})

    def never():
        calls.append("c")
        return StrategyResult("c", "ok", value="should not run")

    chain = ReaderStrategyChain()
    result = chain.execute(
        [("a", fail_a), ("b", ok_b), ("c", never)],
        source_url="u",
        source_kind="video",
    )
    assert result.ok
    assert result.winner is not None
    assert result.winner.value == {"text": "hi"}
    assert [r.name for r in result.tried] == ["a", "b"]
    assert calls == ["a", "b"]
    acq = _to_acq(result)
    assert acq.ok
    assert [a.strategy for a in acq.strategies_tried] == ["a", "b"]


def test_chain_all_fail_suggests_next_capability():
    def fail():
        return StrategyResult("x", "skipped", reason="no captions", reason_code=REASON_NO_CAPTIONS)

    result = ReaderStrategyChain().execute(
        [("x", fail)],
        suggested_next_capability="speech_to_text",
    )
    assert not result.ok
    assert result.suggested_next_capability == "speech_to_text"
    acq = _to_acq(result)
    assert acq.suggested_next_capability == "speech_to_text"
    assert "speech_to_text" in acq.operator_summary


def test_chain_swallows_strategy_exceptions():
    def boom():
        raise RuntimeError("kaboom")

    def ok():
        return StrategyResult("ok", "ok", reason_code="ok", value=1)

    result = ReaderStrategyChain().execute([("boom", boom), ("ok", ok)])
    assert result.ok
    assert result.tried[0].outcome == "error"
    assert "kaboom" in (result.tried[0].reason or "")
