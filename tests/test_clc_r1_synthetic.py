"""CLC.R1-SYNTHETIC — cite path + honest no_match. No orders. Not R1-LIVE."""

from __future__ import annotations

from pathlib import Path

from atlas.investment.clc_r1_fixture import (
    CITE_ID,
    LABORATORY_ID,
    NOMATCH_ID,
    _score_cite,
    _score_nomatch,
    cite_packet,
    nomatch_packet,
    retrieve_e001,
    run_fixture,
)
from atlas.investment.decide_rationale import load_rationale
from atlas.investment.lesson_influence import E001_LESSON_ID
from tests.test_bre3_decide_rationale import _FakeLLM, _FakeResp, _JSON

_CITE_JSON = (
    '{"rationale_text":"Lesson L-E001-buy_name-vol-accel is relevant as caution: '
    'volume acceleration did not add after costs. Falsify if vol-accel beats '
    'momentum+RS in this regime. Bounded L2 ranking only. Never orders.",'
    '"falsifiers":["vol-accel beats momentum+RS after 15bps"],'
    '"expected_outcome":"ranking caution, not a buy",'
    '"claims":[{"text":"cite L-E001-buy_name-vol-accel","evidence_ids":["obs-clc-r1-synth-cite"]}]}'
)
_NOMATCH_JSON = (
    '{"rationale_text":"No retrieved lesson applies. Honest no_match. '
    'Do not invent a lesson.",'
    '"falsifiers":["a matching validated lesson later appears"],'
    '"expected_outcome":"unchanged ranking",'
    '"claims":[{"text":"no_match","evidence_ids":["obs-clc-r1-synth-nomatch"]}]}'
)


class _PathLLM:
    def __init__(self) -> None:
        self.calls = 0
        self.last_messages = None

    def lane_busy(self) -> bool:
        return False

    def for_role(self, role: str) -> "_PathLLM":
        return self

    def chat(self, messages, **kwargs):  # noqa: ANN001
        self.calls += 1
        self.last_messages = messages
        blob = " ".join(str(getattr(m, "content", m) or "") for m in messages).lower()
        if "no retrieved lesson" in blob or "honest no_match" in blob or "fixture.ns" in blob:
            return _FakeResp(_NOMATCH_JSON)
        return _FakeResp(_CITE_JSON)


def test_retrieve_e001_cites_canonical_lesson():
    cited = retrieve_e001()
    ids = {str(x.get("id")) for x in cited if isinstance(x, dict)}
    assert E001_LESSON_ID in ids


def test_packets_never_orders_and_stamp():
    cite = cite_packet()
    assert cite["never_orders"] is True
    assert cite["synthetic"] is True
    assert cite["no_match"] is False
    assert E001_LESSON_ID in cite["lesson_refs"]
    nomatch = nomatch_packet()
    assert nomatch["no_match"] is True
    assert nomatch["lesson_refs"] == []
    assert nomatch["action"] == "buy"  # sidecar only; fixture never fills


def test_cite_scorer_rejects_schema_placeholder():
    scored = _score_cite(
        {
            "status": "done",
            "review_status": "REVIEWED",
            "llm": True,
            "rationale_text": "1-3 sentences",
            "claims": [{"text": "str"}],
        }
    )
    assert scored["placeholder"] is True
    assert scored["ok"] is False
    scored = _score_nomatch(
        {
            "status": "done",
            "review_status": "REVIEWED",
            "llm": True,
            "no_match": True,
            "rationale_text": "Volume acceleration did not add, so skip.",
        }
    )
    assert scored["invented_e001"] is True
    assert scored["ok"] is False


def test_clc_r1_synthetic_both_paths_and_persist(tmp_path: Path):
    llm = _PathLLM()
    report = run_fixture(tmp_path, llm=llm, max_passes=2)
    assert llm.calls == 2
    assert report["never_orders"] is True
    assert report["sma_rsi_untouched"] is True
    assert report["r1_live"] is False
    cite = load_rationale(tmp_path, CITE_ID, laboratory_id=LABORATORY_ID)
    nomatch = load_rationale(tmp_path, NOMATCH_ID, laboratory_id=LABORATORY_ID)
    assert cite is not None and nomatch is not None
    assert cite["status"] == "done"
    assert nomatch["status"] == "done"
    assert cite["review_status"] == "REVIEWED"
    assert nomatch["review_status"] == "REVIEWED"
    assert cite.get("synthetic") is True
    assert nomatch.get("no_match") is True
    assert cite.get("never_orders") is True
    assert report["cite"]["ok"] is True
    assert report["cite"]["cited_e001"] is True
    assert report["nomatch"]["ok"] is True
    assert report["nomatch"]["invented_e001"] is False
    assert report["synthetic_green"] is True
    # Restart/retrieve: sidecars survive a fresh load from disk.
    cite2 = load_rationale(tmp_path, CITE_ID, laboratory_id=LABORATORY_ID)
    nomatch2 = load_rationale(tmp_path, NOMATCH_ID, laboratory_id=LABORATORY_ID)
    assert _score_cite(cite2)["ok"] is True
    assert _score_nomatch(nomatch2)["ok"] is True
    lesson = tmp_path / "investment" / "fel" / "lessons" / f"{E001_LESSON_ID}.json"
    assert lesson.is_file()
    assert _FakeLLM(_JSON).calls == 0
