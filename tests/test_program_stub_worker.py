"""Program stub worker (MI.2)."""

from __future__ import annotations

from atlas.workers.base import TickContext
from atlas.workers.program_stub import ProgramStubWorker


def test_program_stub_journals_waiting_note():
    worker = ProgramStubWorker()
    result = worker.do_tick(
        TickContext(
            worker_id="w1",
            mission_id="m1",
            config={"role": "News Intelligence", "roadmap": "MI.4"},
            config_version=1,
            state={},
        )
    )
    assert result.done is False
    assert result.state["ticks"] == 1
    assert "News Intelligence" in result.note
    assert "MI.4" in result.note
    assert "stub:" in result.note
