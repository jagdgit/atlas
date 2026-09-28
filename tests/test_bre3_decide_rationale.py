"""BRE.3 — decide-time async LLM rationale hermetic tests."""

from __future__ import annotations

from atlas.investment.decide_rationale import (
    budget_for_decision,
    drain_pending_rationales,
    format_decide_rationale_lines,
    load_rationale,
    schedule_decide_rationale,
)


class _FakeResp:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeRole:
    def __init__(self, text: str, owner: "_FakeLLM | None" = None) -> None:
        self._text = text
        self._owner = owner

    def chat(self, messages, **kwargs):  # noqa: ANN001
        if self._owner is not None:
            self._owner.calls += 1
            self._owner.last_messages = messages
            self._owner.last_kwargs = kwargs
        return _FakeResp(self._text)


class _FakeLLM:
    def __init__(self, text: str, *, busy: bool = False) -> None:
        self._text = text
        self._busy = busy
        self.calls = 0
        self.last_messages = None
        self.last_kwargs = None

    def lane_busy(self) -> bool:
        return self._busy

    def for_role(self, role: str) -> _FakeRole:
        return _FakeRole(self._text, owner=self)


_JSON = (
    '{"rationale_text":"Buy on thesis strength with PE known.",'
    '"falsifiers":["FCF stays missing","sector RS breaks"],'
    '"expected_outcome":"outperform peers over 30d",'
    '"claims":[{"text":"thesis ok","evidence_ids":["obs-1"]}]}'
)


def test_budget_buy_high():
    bud = budget_for_decision(action="buy", unknowns=["fcf", "news", "de"], is_open_book=True)
    assert bud["llm_budget"] >= 1


def test_schedule_pending_no_llm(tmp_path):
    packet = {
        "decision_id": "dec-bre3-1",
        "symbol": "EICHERMOT.NS",
        "action": "buy",
        "reasons_for": ["thesis trigger"],
        "unknowns": ["fcf"],
        "observation_ids": ["obs-1"],
        "meta": {"llm_pending": True},
    }
    row = schedule_decide_rationale(
        tmp_path,
        decision_id="dec-bre3-1",
        symbol="EICHERMOT.NS",
        action="buy",
        laboratory_id="india_equity_learner",
        packet=packet,
    )
    assert row is not None
    assert row["status"] == "pending"
    assert row["llm"] is False
    # Idempotent
    row2 = schedule_decide_rationale(
        tmp_path,
        decision_id="dec-bre3-1",
        symbol="EICHERMOT.NS",
        action="buy",
        laboratory_id="india_equity_learner",
        packet=packet,
    )
    assert row2["rationale_id"] == row["rationale_id"]


def test_drain_fills_sidecar_packet_unchanged(tmp_path):
    packet = {
        "decision_id": "dec-bre3-2",
        "symbol": "APOLLOHOSP.NS",
        "action": "buy",
        "reasons_for": ["rank1"],
        "unknowns": ["fcf"],
        "observation_ids": ["obs-1"],
    }
    schedule_decide_rationale(
        tmp_path,
        decision_id="dec-bre3-2",
        symbol="APOLLOHOSP.NS",
        action="buy",
        laboratory_id="lab",
        packet=packet,
    )
    llm = _FakeLLM(_JSON)
    out = drain_pending_rationales(
        tmp_path, laboratory_id="lab", llm=llm, max_passes=3
    )
    assert out["done"] == 1
    assert llm.calls >= 1
    row = load_rationale(tmp_path, "dec-bre3-2", laboratory_id="lab")
    assert row is not None
    assert row["status"] == "done"
    assert row.get("review_status") == "REVIEWED"
    assert row.get("evidence_packet")
    assert "thesis" in (row.get("rationale_text") or "").lower() or row.get("rationale_text")
    assert row.get("falsifiers")
    # Packet dict not mutated by drain
    assert packet.get("meta") is None or "rationale_text" not in (packet.get("meta") or {})


def test_drain_unreviewed_when_non_json(tmp_path):
    schedule_decide_rationale(
        tmp_path,
        decision_id="dec-bad",
        symbol="TCS.NS",
        action="buy",
        laboratory_id="lab",
        packet={
            "decision_id": "dec-bad",
            "action": "buy",
            "symbol": "TCS.NS",
            "unknowns": ["fcf"],
            "observation_ids": ["obs-1"],
        },
    )
    llm = _FakeLLM("not json at all")
    out = drain_pending_rationales(
        tmp_path, laboratory_id="lab", llm=llm, max_passes=3
    )
    assert out["failed"] >= 1 or out["skipped"] >= 1
    row = load_rationale(tmp_path, "dec-bad", laboratory_id="lab")
    assert row["review_status"] == "UNREVIEWED"
    assert row["status"] != "done"


def test_drain_defers_when_lane_busy(tmp_path):
    schedule_decide_rationale(
        tmp_path,
        decision_id="dec-busy",
        symbol="TCS.NS",
        action="sell",
        laboratory_id="lab",
        packet={"decision_id": "dec-busy", "action": "sell", "symbol": "TCS.NS", "unknowns": ["x"]},
    )
    llm = _FakeLLM(_JSON, busy=True)
    out = drain_pending_rationales(
        tmp_path, laboratory_id="lab", llm=llm, max_passes=3
    )
    assert out["deferred"] >= 1
    assert llm.calls == 0
    row = load_rationale(tmp_path, "dec-busy", laboratory_id="lab")
    assert row["status"] == "deferred_lane_busy"


def test_drain_skips_below_budget(tmp_path):
    # Force zero budget by writing a hold-like low-importance then overriding
    row = schedule_decide_rationale(
        tmp_path,
        decision_id="dec-low",
        symbol="INFY.NS",
        action="buy",
        laboratory_id="lab",
        packet={"decision_id": "dec-low", "action": "buy", "symbol": "INFY.NS", "unknowns": []},
    )
    assert row is not None
    # Cap max_passes to 0 effectively by setting budget 0 on disk
    path = tmp_path / "investment" / "decide_rationale" / "lab" / "by_id" / "dec-low.json"
    import json

    doc = json.loads(path.read_text())
    doc["llm_budget"] = 0
    path.write_text(json.dumps(doc))
    llm = _FakeLLM(_JSON)
    out = drain_pending_rationales(
        tmp_path, laboratory_id="lab", llm=llm, max_passes=3
    )
    assert out["skipped"] >= 1
    assert llm.calls == 0


def test_evening_formatter_joins(tmp_path):
    schedule_decide_rationale(
        tmp_path,
        decision_id="dec-fmt",
        symbol="RELIANCE.NS",
        action="buy",
        laboratory_id="lab",
        packet={
            "decision_id": "dec-fmt",
            "action": "buy",
            "symbol": "RELIANCE.NS",
            "unknowns": ["fcf"],
            "observation_ids": ["obs-1"],
        },
    )
    drain_pending_rationales(
        tmp_path, laboratory_id="lab", llm=_FakeLLM(_JSON), max_passes=3
    )
    packets = [
        {
            "decision_id": "dec-fmt",
            "action": "buy",
            "symbol": "RELIANCE.NS",
            "meta": {"llm_pending": True},
        }
    ]
    lines = format_decide_rationale_lines(
        tmp_path, packets, laboratory_id="lab"
    )
    assert any("Decide-time rationale" in x for x in lines)
    assert any("RELIANCE" in x for x in lines)
    assert any("falsifiers" in x for x in lines)


def test_schedule_skips_holds(tmp_path):
    assert (
        schedule_decide_rationale(
            tmp_path,
            decision_id="h1",
            symbol="X.NS",
            action="hold",
            laboratory_id="lab",
        )
        is None
    )


def test_clc_r0_buy_budget_3_still_drains_under_cap_2(tmp_path):
    """Material buys scored llm_budget=3; max_passes=2 used to pick nobody."""
    schedule_decide_rationale(
        tmp_path,
        decision_id="dec-buy-cap",
        symbol="IDEA.NS",
        action="buy",
        laboratory_id="lab",
        packet={
            "decision_id": "dec-buy-cap",
            "action": "buy",
            "symbol": "IDEA.NS",
            "unknowns": ["fcf", "news", "pe"],
            "observation_ids": ["obs-1"],
        },
    )
    llm = _FakeLLM(_JSON)
    out = drain_pending_rationales(
        tmp_path, laboratory_id="lab", llm=llm, max_passes=2
    )
    assert out["done"] == 1
    assert llm.calls >= 1
    row = load_rationale(tmp_path, "dec-buy-cap", laboratory_id="lab")
    assert row["status"] == "done"
    assert row["llm"] is True


def test_clc_r0_unchosen_stay_pending_not_skipped_no_budget(tmp_path):
    for i, sym in enumerate(["AAA.NS", "BBB.NS"]):
        schedule_decide_rationale(
            tmp_path,
            decision_id=f"dec-pair-{i}",
            symbol=sym,
            action="buy",
            laboratory_id="lab",
            packet={
                "decision_id": f"dec-pair-{i}",
                "action": "buy",
                "symbol": sym,
                "unknowns": ["fcf"],
                "observation_ids": ["obs-1"],
            },
        )
    llm = _FakeLLM(_JSON)
    out = drain_pending_rationales(
        tmp_path, laboratory_id="lab", llm=llm, max_passes=1
    )
    assert out["done"] == 1
    assert out["left_pending"] == 1
    statuses = {
        load_rationale(tmp_path, f"dec-pair-{i}", laboratory_id="lab")["status"]
        for i in range(2)
    }
    assert "done" in statuses
    assert "pending" in statuses
    assert "skipped_no_budget" not in statuses


def test_clc_r0_expires_stale_backlog(tmp_path):
    from atlas.investment.decide_rationale import expire_stale_rationales

    row = schedule_decide_rationale(
        tmp_path,
        decision_id="dec-old",
        symbol="TCS.NS",
        action="buy",
        laboratory_id="lab",
        packet={"decision_id": "dec-old", "action": "buy", "symbol": "TCS.NS"},
    )
    assert row is not None
    path = tmp_path / "investment" / "decide_rationale" / "lab" / "by_id" / "dec-old.json"
    import json

    doc = json.loads(path.read_text())
    doc["created_at"] = "2026-09-01T10:00:00Z"
    path.write_text(json.dumps(doc))
    n = expire_stale_rationales(
        tmp_path, laboratory_id="lab", keep_ist_date="2026-09-22"
    )
    assert n == 1
    stale = load_rationale(tmp_path, "dec-old", laboratory_id="lab")
    assert stale["status"] == "skipped_stale"
    assert stale["llm"] is False


def test_clc_r1_save_survives_datetime_in_sidecar(tmp_path):
    """Live miss: LLM ran, sidecar save TypeError on datetime published_at."""
    from datetime import datetime, timezone

    from atlas.investment.decide_rationale import _save

    row = schedule_decide_rationale(
        tmp_path,
        decision_id="dec-dt",
        symbol="IDEA.NS",
        action="buy",
        laboratory_id="lab",
        packet={
            "decision_id": "dec-dt",
            "action": "buy",
            "symbol": "IDEA.NS",
            "unknowns": ["fcf"],
            "observation_ids": ["obs-1"],
        },
    )
    assert row is not None
    row["world_evidence"] = {
        "news": [
            {
                "title": "x",
                "published_at": datetime(2026, 9, 22, tzinfo=timezone.utc),
            }
        ]
    }
    _save(tmp_path, "lab", row)
    loaded = load_rationale(tmp_path, "dec-dt", laboratory_id="lab")
    assert loaded is not None
    assert "2026-09-22" in str(loaded["world_evidence"])


def test_clc_r1_prompt_includes_lesson_refs(tmp_path):
    schedule_decide_rationale(
        tmp_path,
        decision_id="dec-lesson",
        symbol="HBLPOWER.NS",
        action="buy",
        laboratory_id="lab",
        packet={
            "decision_id": "dec-lesson",
            "action": "buy",
            "symbol": "HBLPOWER.NS",
            "unknowns": ["fcf"],
            "observation_ids": ["obs-1"],
            "lesson_refs": ["E001-buy_name-vol-accel"],
            "experience_refs": ["E001-buy_name-vol-accel"],
            "no_match": False,
            "belief_context": {"influence": "cited_bounded"},
        },
    )
    llm = _FakeLLM(_JSON)
    drain_pending_rationales(tmp_path, laboratory_id="lab", llm=llm, max_passes=2)
    parts = []
    for m in llm.last_messages or []:
        if hasattr(m, "content"):
            parts.append(str(m.content))
        elif isinstance(m, dict):
            parts.append(str(m.get("content") or ""))
        else:
            parts.append(str(m))
    blob = " ".join(parts)
    assert "E001-buy_name-vol-accel" in blob
    assert "lesson_refs" in blob
    assert "evidence_packet" not in blob
    row = load_rationale(tmp_path, "dec-lesson", laboratory_id="lab")
    assert row["status"] == "done"
    assert row.get("lesson_refs") == ["E001-buy_name-vol-accel"]


def test_clc_r1_skips_pre_stamp_backlog_without_llm(tmp_path):
    """Live 2026-09-22 pending IDEA files lack lesson_refs/no_match keys."""
    import json

    from atlas.investment.decide_rationale import expire_pre_clc_rationales

    schedule_decide_rationale(
        tmp_path,
        decision_id="dec-old-shape",
        symbol="IDEA.NS",
        action="buy",
        laboratory_id="lab",
        packet={
            "decision_id": "dec-old-shape",
            "action": "buy",
            "symbol": "IDEA.NS",
            "unknowns": ["fcf"],
            "observation_ids": ["obs-1"],
        },
    )
    path = tmp_path / "investment" / "decide_rationale" / "lab" / "by_id" / "dec-old-shape.json"
    doc = json.loads(path.read_text())
    summary = dict(doc.get("packet_summary") or {})
    summary.pop("lesson_refs", None)
    summary.pop("no_match", None)
    summary.pop("experience_refs", None)
    doc["packet_summary"] = summary
    doc.pop("lesson_refs", None)
    path.write_text(json.dumps(doc))
    llm = _FakeLLM(_JSON)
    out = drain_pending_rationales(tmp_path, laboratory_id="lab", llm=llm, max_passes=2)
    assert out.get("pre_clc_expired") == 1
    assert llm.calls == 0
    skipped = load_rationale(tmp_path, "dec-old-shape", laboratory_id="lab")
    assert skipped["status"] == "skipped_pre_clc"
    assert skipped["llm"] is False
    n = expire_pre_clc_rationales(tmp_path, laboratory_id="lab")
    assert n == 0


def test_clc_r1_honest_no_match_still_drains(tmp_path):
    schedule_decide_rationale(
        tmp_path,
        decision_id="dec-nomatch",
        symbol="PATANJALI.NS",
        action="buy",
        laboratory_id="lab",
        packet={
            "decision_id": "dec-nomatch",
            "action": "buy",
            "symbol": "PATANJALI.NS",
            "unknowns": ["fcf"],
            "observation_ids": ["obs-1"],
            "lesson_refs": [],
            "no_match": True,
        },
    )
    llm = _FakeLLM(_JSON)
    out = drain_pending_rationales(tmp_path, laboratory_id="lab", llm=llm, max_passes=2)
    assert out["done"] == 1
    assert llm.calls >= 1


def test_clc_r1_quota_skips_rest_after_llm_shot(tmp_path):
    """Live 2026-09-23: 10 COALINDIA echoes; do not drain remaining wash."""
    import json
    from datetime import datetime, timezone

    from atlas.investment.decide_rationale import expire_r1_quota_rationales

    schedule_decide_rationale(
        tmp_path,
        decision_id="dec-first",
        symbol="COALINDIA.NS",
        action="buy",
        laboratory_id="lab",
        packet={
            "decision_id": "dec-first",
            "action": "buy",
            "symbol": "COALINDIA.NS",
            "lesson_refs": [],
            "no_match": True,
            "unknowns": ["fcf"],
            "observation_ids": ["obs-1"],
        },
    )
    schedule_decide_rationale(
        tmp_path,
        decision_id="dec-rest",
        symbol="IDEA.NS",
        action="sell",
        laboratory_id="lab",
        packet={
            "decision_id": "dec-rest",
            "action": "sell",
            "symbol": "IDEA.NS",
            "lesson_refs": [],
            "no_match": True,
            "unknowns": ["fcf"],
            "observation_ids": ["obs-2"],
        },
    )
    path = tmp_path / "investment" / "decide_rationale" / "lab" / "by_id" / "dec-first.json"
    doc = json.loads(path.read_text())
    doc["llm"] = True
    doc["status"] = "failed"
    doc["completed_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    path.write_text(json.dumps(doc))
    n = expire_r1_quota_rationales(tmp_path, laboratory_id="lab")
    assert n == 1
    rest = load_rationale(tmp_path, "dec-rest", laboratory_id="lab")
    assert rest["status"] == "skipped_r1_quota"
    llm = _FakeLLM(_JSON)
    out = drain_pending_rationales(tmp_path, laboratory_id="lab", llm=llm, max_passes=2)
    assert llm.calls == 0
    assert out.get("r1_quota_expired") == 0
