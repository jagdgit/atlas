"""Intelligence Programs (MI.1)."""

from __future__ import annotations

from atlas.missions.programs import (
    BUILTIN_PROGRAMS,
    MEMBER_ENABLED,
    MEMBER_STUB,
    ProgramService,
    get_program,
    lifecycle_board,
    list_programs,
    program_label,
)


def test_builtin_programs_include_market_engineering_personal():
    ids = {p.id for p in list_programs()}
    assert ids == {
        "market_intelligence",
        "engineering_intelligence",
        "personal_intelligence",
    }


def test_market_program_has_seven_members_with_stubs():
    market = get_program("market_intelligence")
    assert market is not None
    assert len(market.members) == 7
    statuses = {m.template: m.status for m in market.members}
    assert statuses["decision_simulation"] == MEMBER_ENABLED
    assert statuses["market_observer"] == MEMBER_ENABLED
    assert statuses["news_intelligence"] == MEMBER_ENABLED
    assert statuses["event_research"] == MEMBER_ENABLED
    assert statuses["company_intelligence"] == MEMBER_STUB
    assert "Broker Profiles" in market.domain_adapters
    assert "MarketReader" in market.domain_adapters


def test_lifecycle_board_covers_all_stages():
    board = lifecycle_board(get_program("market_intelligence").lifecycle)
    assert len(board) == 7
    assert board[0]["label"] == "Observe"
    assert any(r["stage"] == "decide" and r["status"] == "active" for r in board)


def test_program_service_describe_without_deps():
    svc = ProgramService()
    view = svc.describe("market_intelligence")
    assert view["title"] == "Market Intelligence"
    assert view["startable_count"] == 0  # no templates wired
    assert view["stub_count"] >= 3
    assert view["label"] == program_label("market_intelligence")
    assert len(view["lifecycle"]) == 7


def test_program_service_describe_with_fake_templates():
    class _T:
        def __init__(self, name: str, tid: str):
            self.name = name
            self.id = tid

    class _Templates:
        def list_templates(self):
            return [_T("decision_simulation", "tpl-1"), _T("repository_learning", "tpl-2")]

    svc = ProgramService(templates=_Templates())
    market = svc.describe("market_intelligence")
    decision = next(m for m in market["members"] if m["template"] == "decision_simulation")
    assert decision["can_start"] is True
    assert decision["status"] == MEMBER_ENABLED
    assert market["startable_count"] >= 1

    eng = svc.describe("engineering_intelligence")
    repo = next(m for m in eng["members"] if m["template"] == "repository_learning")
    assert repo["can_start"] is True


def test_context_spike_empty_without_knowledge():
    svc = ProgramService()
    ctx = svc.context("inflation", program_id="market_intelligence")
    assert ctx["spike"] is True
    assert ctx["topic"] == "inflation"
    assert ctx["items"] == []


def test_context_spike_uses_findings():
    class _Knowledge:
        def list_findings(self, *, limit: int = 50):
            return [
                {
                    "id": "1",
                    "statement": "Inflation reduces purchasing power",
                    "claim_type": "relationship",
                    "domain": "external",
                },
                {
                    "id": "2",
                    "statement": "Unrelated claim about weather",
                    "claim_type": "claim",
                },
            ]

        def retrieve(self, query: str, k: int = 5):
            return []

    svc = ProgramService(knowledge=_Knowledge())
    ctx = svc.context("inflation")
    assert ctx["count"] == 1
    assert ctx["items"][0]["kind"] == "finding"


def test_start_skips_stubs_and_starts_compat():
    created: list[dict] = []

    class _Mission:
        def __init__(self, mid: str):
            self.id = mid
            self.status = "active"

    class _Templates:
        def list_templates(self):
            class T:
                name = "decision_simulation"
                id = "tpl-ds"

            return [T()]

        def instantiate(self, template_name, **kwargs):
            created.append({"template": template_name, **kwargs})
            return {"mission": _Mission("m-1")}

    class _Missions:
        def list_missions(self, **kwargs):
            return []

    svc = ProgramService(templates=_Templates(), missions=_Missions())
    result = svc.start("market_intelligence")
    assert len(result["started"]) == 1
    assert result["started"][0]["template"] == "decision_simulation"
    assert any(s["reason"] == "stub" for s in result["skipped"])
    assert created[0]["labels"][0] == "program:market_intelligence"
    assert BUILTIN_PROGRAMS[0].id == "market_intelligence"
