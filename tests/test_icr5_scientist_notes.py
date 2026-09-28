"""OI-ICR5 — scientist notes (advice-only)."""

from __future__ import annotations

from atlas.investment.allocation_comparison import (
    DECISION_EXIT_REVIEW,
    build_allocation_comparison_packet,
)
from atlas.investment.incumbent_scientist import (
    draft_scientist_notes,
    drain_pending_scientist_notes,
    enrich_with_llm,
    schedule_from_lab_acps,
    schedule_scientist_notes,
)
from atlas.investment.llm_lanes import cu_lane_for_role


def _acp_exit():
    hold = {
        "symbol": "CIPLA.NS",
        "qty": 15,
        "mark": 1438.0,
        "avg_price": 1460.0,
        "score": 0.5,
        "confidence": "very_low",
        "components": {"momentum": 0.55},
    }
    aw = {
        "thesis": {
            "stance": "avoid",
            "summary": "Avoid — MoS deep negative.",
            "id": "th-1",
        },
        "valuation": {"margin_of_safety_pct": -55.0},
    }
    return build_allocation_comparison_packet(
        hold=hold,
        challengers=[
            {
                "symbol": "INFY.NS",
                "score": 0.8,
                "confidence": "high",
                "components": {"momentum": 0.8},
            }
        ],
        cash=20_000.0,
        laboratory_id="india_equity_learner",
        awareness=aw,
        equity=80_000.0,
    )


def test_draft_flags_contradictions_and_never_orders():
    acp = _acp_exit()
    assert acp["decision"] == DECISION_EXIT_REVIEW
    notes = draft_scientist_notes(
        acp, resolution={"action": "WAIT", "waiting_for": ["identity_repair"]}
    )
    assert notes["advice_only"] is True
    assert notes["never_orders"] is True
    assert notes["llm"] is False
    assert any("AVOID" in c or "allocated" in c.lower() for c in notes["contradictions"])
    assert notes["unknowns_that_flip_ranking"]
    assert notes["flip_hints"]
    assert "robust" in notes["incumbent_edge_robust"].lower() or "edge" in notes[
        "incumbent_edge_robust"
    ].lower()


def test_schedule_attaches_to_acp(tmp_path):
    acp = _acp_exit()
    row = schedule_scientist_notes(
        tmp_path,
        acp,
        laboratory_id="india_equity_learner",
        resolution={"action": "EXIT_TO_CASH", "reason_code": "exit_avoid_to_cash"},
    )
    assert row is not None
    assert row["notes"]["never_orders"] is True
    assert acp.get("scientist_notes")
    assert acp["scientist_notes"]["advice_only"] is True
    # Idempotent per state_hash even when paper tick mints a fresh acp_id
    acp2 = dict(acp)
    acp2["acp_id"] = "fresh-uuid-should-not-reschedule"
    row2 = schedule_scientist_notes(
        tmp_path, acp2, laboratory_id="india_equity_learner"
    )
    assert row2["notes_id"] == row["notes_id"]


def test_scientist_role_maps_to_research_lane():
    assert cu_lane_for_role("scientist") == "research"


def test_enrich_without_llm_keeps_draft(tmp_path):
    acp = _acp_exit()
    row = schedule_scientist_notes(tmp_path, acp, laboratory_id="india_equity_learner")
    out = enrich_with_llm(
        tmp_path, row, laboratory_id="india_equity_learner", llm=None
    )
    assert out["llm_status"] == "skipped_no_llm"
    assert out["notes"]["source"] == "deterministic"
    assert out["notes"]["review_status"] == "UNREVIEWED"


class _FakeLLM:
    def for_role(self, role):
        assert role in {"scientist", "researcher"}
        return self

    def lane_busy(self):
        return False

    def chat(self, messages, **kwargs):
        class R:
            text = (
                '{"contradictions":["tech vs avoid"],'
                '"unknowns_that_flip_ranking":["identity_repair"],'
                '"incumbent_edge_robust":"Not robust under quarantine",'
                '"summary":"CIPLA: EXIT_REVIEW — repair identity before trusting edge."}'
            )

        return R()


def test_enrich_with_fake_llm(tmp_path):
    acp = _acp_exit()
    row = schedule_scientist_notes(tmp_path, acp, laboratory_id="india_equity_learner")
    out = enrich_with_llm(
        tmp_path, row, laboratory_id="india_equity_learner", llm=_FakeLLM()
    )
    assert out["llm_status"] == "done"
    assert out["notes"]["llm"] is True
    assert out["notes"]["never_orders"] is True
    assert out["notes"]["review_status"] == "REVIEWED"
    assert "identity" in out["notes"]["summary"].lower() or "EXIT" in out["notes"][
        "summary"
    ]


def test_enrich_reasoning_exception_unreviewed(tmp_path):
    class BoomRS:
        def reason_scientist(self, **kwargs):
            raise AttributeError("simulated")

    acp = _acp_exit()
    row = schedule_scientist_notes(tmp_path, acp, laboratory_id="india_equity_learner")
    out = enrich_with_llm(
        tmp_path,
        row,
        laboratory_id="india_equity_learner",
        llm=_FakeLLM(),
        reasoning=BoomRS(),
    )
    # AttributeError is a bug-class failure — permanent, no retry storm
    assert out["llm_status"] == "failed_permanent"
    assert "AttributeError" in str(out.get("fail_reason") or "")
    assert out["notes"]["review_status"] == "UNREVIEWED"
    assert out["notes"]["never_orders"] is True


def test_list_pending_retries_attribute_error(tmp_path):
    import json
    from pathlib import Path

    from atlas.investment.incumbent_scientist import (
        list_pending_llm,
        retire_exhausted_scientist_notes,
    )

    acp = _acp_exit()
    row = schedule_scientist_notes(tmp_path, acp, laboratory_id="india_equity_learner")
    row["llm_status"] = "failed:AttributeError"
    path = Path(row["path"])
    path.write_text(json.dumps(row, indent=2) + "\n", encoding="utf-8")
    # Historical AttributeError leftovers are retired without another LLM burn
    retire_exhausted_scientist_notes(tmp_path, laboratory_id="india_equity_learner")
    pending = list_pending_llm(tmp_path, laboratory_id="india_equity_learner")
    assert not any(p.get("notes_id") == row.get("notes_id") for p in pending)


def test_batch_and_drain(tmp_path):
    acp = _acp_exit()
    batch = schedule_from_lab_acps(
        tmp_path,
        [acp],
        laboratory_id="india_equity_learner",
        resolutions=[{"symbol": "CIPLA.NS", "action": "WAIT"}],
    )
    assert batch["count"] == 1
    meta = drain_pending_scientist_notes(
        tmp_path,
        laboratory_id="india_equity_learner",
        llm=None,
        max_passes=2,
    )
    assert meta["skipped"] >= 1 or meta["pending"] >= 0


def test_compact_legacy_duplicates(tmp_path):
    import json
    from pathlib import Path

    from atlas.investment.incumbent_scientist import (
        compact_legacy_scientist_notes,
        schedule_scientist_notes,
    )

    acp = _acp_exit()
    sh = acp["state_hash"]
    sym = "CIPLA.NS"
    root = tmp_path / "investment" / "scientist_notes" / "india_equity_learner" / "by_id"
    root.mkdir(parents=True)
    for i, st in enumerate(("pending", "failed:AttributeError", "done")):
        doc = {
            "version": "icr.5",
            "notes_id": f"id-{i}",
            "acp_id": f"acp-{i}",
            "state_hash": sh,
            "symbol": sym,
            "llm_status": st,
            "notes": {
                "review_status": "REVIEWED" if st == "done" else "DETERMINISTIC",
                "never_orders": True,
            },
        }
        (root / f"dup-{i}.json").write_text(json.dumps(doc) + "\n", encoding="utf-8")

    out = compact_legacy_scientist_notes(
        tmp_path, laboratory_id="india_equity_learner", dry_run=False
    )
    assert out["archived"] == 2
    assert len(list(root.glob("*.json"))) == 1
    assert len(list((root / "_archive_duplicates").glob("*.json"))) == 2
    kept = json.loads(list(root.glob("*.json"))[0].read_text())
    assert kept["llm_status"] == "done"
