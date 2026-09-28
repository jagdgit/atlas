"""M4 Step 4 — canonical fundamentals → deterministic finding → embedding → RAG.

S4.1–S4.8. No ranking retune. No LLM in the summary builder. Two-symbol slice.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

from atlas.agents.rag_agent import RagAgent
from atlas.investment.fundamental_knowledge import (
    DEFAULT_SLICE_SYMBOLS,
    publish_symbol,
    run_tick,
)
from atlas.investment.fundamental_summary import CLAIM_TYPE, build_fundamental_summary
from atlas.investment.nse_xbrl.calculations import DEBT_DEFINITION_ID
from atlas.knowledge.access import TIER_FINDINGS
from atlas.knowledge.lifecycle import finding_identity_key
from atlas.llm.provider import LLMResponse
from tests.test_knowledge import FakeEmbedResponse, FakeLLM, _service
from tests.test_lab_loop0_findings_rag import FakeFindingEmb, FakeFindingRepo

ROOT = Path(__file__).resolve().parents[1]


HBLPOWER_ROW = {
    "symbol": "HBLPOWER.NS",
    "pe": 25.859135760462742,
    "roe": 44.08399367041512,
    "debt_to_equity": 0.019866861767468748,
    "fcf": 6293200000.0,
    "sector": "Capital Goods",
    "source": "nse_xbrl",
    "as_of": "2026-09-18",
    "eps_basis": "FY",
    "name": "HBL Power",
    "nse_raw_evidence_id": "ea71f0eab3516163bee183b9629ef0cb336e380d04bbe2ee0c4b41588063e9e6",
    "evidence_conflicts": [
        "pe_conflict",
        {
            "conflict_type": "DEBT_DEFINITION",
            "field": "debt_to_equity",
            "note": "IFIndAs BorrowingsCurrent/Noncurrent may include Ind AS 116 lease liabilities.",
        },
    ],
    "evidence": {
        "pe": [
            {
                "as_of": "2026-09-18",
                "recorded_at": "2026-09-18T18:06:56Z",
                "source": "nse_xbrl",
                "value": 93.72409954848966,
            },
            {
                "as_of": "2026-09-18",
                "recorded_at": "2026-09-19T02:53:05Z",
                "source": "nse_xbrl",
                "value": 25.859135760462742,
            },
        ],
        "roe": [
            {
                "as_of": "2026-09-18",
                "recorded_at": "2026-09-19T02:53:05Z",
                "source": "nse_xbrl",
                "value": 44.08399367041512,
            }
        ],
        "debt_to_equity": [
            {
                "as_of": "2026-09-18",
                "recorded_at": "2026-09-19T02:53:05Z",
                "source": "nse_xbrl",
                "value": 0.019866861767468748,
            }
        ],
        "fcf": [
            {
                "as_of": "2026-09-18",
                "recorded_at": "2026-09-19T02:53:05Z",
                "source": "nse_xbrl",
                "value": 6293200000.0,
            }
        ],
    },
}

TATACHEM_ROW = {
    "symbol": "TATACHEM.NS",
    "roe": -8.85981308411215,
    "debt_to_equity": 0.3772988776761294,
    "fcf": 640000000.0,
    "sector": "Chemicals",
    "source": "nse_xbrl",
    "as_of": "2026-09-19",
    "eps_basis": "FY",
    "name": "Tata Chemicals",
    "nse_raw_evidence_id": "b384a58619ccc4856c19cae45e81acefd7538b1ddd07cf74cafa573461eedfc3",
    "evidence_conflicts": [
        {
            "conflict_type": "DEBT_DEFINITION",
            "field": "debt_to_equity",
            "note": "IFIndAs BorrowingsCurrent/Noncurrent may include Ind AS 116 lease liabilities.",
        }
    ],
    "evidence": {
        "pe": [
            {
                "as_of": "2026-09-18",
                "recorded_at": "2026-09-18T18:06:56Z",
                "source": "nse_xbrl",
                "value": -3.9885357548240634,
            }
        ],
        "roe": [
            {
                "as_of": "2026-09-19",
                "recorded_at": "2026-09-19T12:09:25Z",
                "source": "nse_xbrl",
                "value": -8.85981308411215,
            }
        ],
        "debt_to_equity": [
            {
                "as_of": "2026-09-19",
                "recorded_at": "2026-09-19T12:09:25Z",
                "source": "nse_xbrl",
                "value": 0.3772988776761294,
            }
        ],
        "fcf": [
            {
                "as_of": "2026-09-19",
                "recorded_at": "2026-09-19T12:09:25Z",
                "source": "nse_xbrl",
                "value": 640000000.0,
            }
        ],
    },
}

CLEAN_ROW = {
    "symbol": "CLEANCO.NS",
    "pe": 12.5,
    "roe": 18.0,
    "debt_to_equity": 0.25,
    "fcf": 1000000.0,
    "sector": "Chemicals",
    "source": "nse_xbrl",
    "as_of": "2026-09-01",
    "eps_basis": "FY",
    "name": "Clean Co",
    "nse_raw_evidence_id": "clean-filing-1",
    "evidence_conflicts": [],
    "evidence": {
        "pe": [
            {
                "as_of": "2026-09-01",
                "recorded_at": "2026-09-01T00:00:00Z",
                "source": "nse_xbrl",
                "value": 12.5,
            }
        ]
    },
}


class SummaryFindingRepo(FakeFindingRepo):
    def __init__(self):
        super().__init__()
        self._n = 0

    def create(self, statement, **kwargs):
        self._n += 1
        fid = str(kwargs.get("finding_id") or f"f-sum-{self._n}")
        row = {
            "id": fid,
            "finding_id": fid,
            "canonical_id": kwargs.get("canonical_id") or f"F-S4{self._n:04d}",
            "revision": kwargs.get("revision", 1),
            "statement": statement,
            "value": kwargs.get("value"),
            "claim_type": kwargs.get("claim_type", CLAIM_TYPE),
            "status": kwargs.get("status", "active"),
            "domain": kwargs.get("domain", "research"),
            "provenance": kwargs.get("provenance") or {},
            "identity_key": list(kwargs.get("identity_key") or []),
            "created_at": "2026-09-19T12:00:00+00:00",
            "supersedes": kwargs.get("supersedes"),
        }
        self.rows.append(row)
        return row

    def find_active_by_identity(self, identity):
        want = list(identity)
        for row in reversed(self.rows):
            if row.get("status") not in {"active", "contested"}:
                continue
            if list(row.get("identity_key") or []) == want:
                return row
        return None

    def append_revision(self, previous, data):
        new = self.create(
            str(data.get("statement", previous.get("statement", ""))),
            canonical_id=previous["canonical_id"],
            revision=int(previous.get("revision", 1)) + 1,
            value=data.get("value"),
            claim_type=data.get("claim_type", CLAIM_TYPE),
            status="active",
            domain=data.get("domain", "research"),
            provenance=data.get("provenance"),
            identity_key=list(finding_identity_key(data)),
            supersedes=previous["id"],
        )
        self.set_status(previous["id"], "superseded", superseded_by=new["id"])
        return new

    def set_status(self, finding_id, status, *, superseded_by=None):
        for row in self.rows:
            if str(row.get("id")) == str(finding_id) or str(row.get("finding_id")) == str(
                finding_id
            ):
                row["status"] = status
                if superseded_by:
                    row["superseded_by"] = superseded_by
                return row
        return None


class KeywordEmbedLLM(FakeLLM):
    """Axes so HBLPOWER / TATACHEM queries are not the same zero vector."""

    def embed(self, texts, **kw):
        del kw
        vecs = []
        for t in texts:
            low = t.lower()
            vecs.append(
                [
                    1.0 if "hblpower" in low else 0.0,
                    1.0 if "tatachem" in low else 0.0,
                    1.0 if "conflict" in low else 0.0,
                    1.0 if "unknown" in low or "blocked" in low else 0.0,
                ]
            )
        return FakeEmbedResponse(vecs)


class GroundedLLM(KeywordEmbedLLM):
    def __init__(self):
        super().__init__()
        self.last_messages = None
        self.calls = 0

    def chat(self, messages, **kw):
        del kw
        self.calls += 1
        self.last_messages = messages
        blob = "\n".join(str(getattr(m, "content", m)) for m in messages)
        question = blob
        if "Question:" in blob:
            question = blob.rsplit("Question:", 1)[-1]
        q = question.lower()
        if "tatachem" in q and "pe" in q:
            return LLMResponse(
                text=(
                    "TATACHEM PE is UNKNOWN because EPS is non-positive "
                    "(non_positive_eps) [1]. The stale -3.99 is invalid and must "
                    "not be used. PE is not 0."
                ),
                model="fake-chat",
                usage={"tokens": 28},
            )
        if "tatachem" in q and "blocked" in q:
            return LLMResponse(
                text="TATACHEM is still blocked: PLC.A INCOMPLETE because PE is UNKNOWN [1].",
                model="fake-chat",
                usage={"tokens": 18},
            )
        if "hblpower" in q and "conflict" in q:
            return LLMResponse(
                text=(
                    "HBLPOWER has recorded conflicts: PE evidence 93.72 vs 25.86 and "
                    "DEBT_DEFINITION [1]. The finding does not silently choose a winner."
                ),
                model="fake-chat",
                usage={"tokens": 26},
            )
        if "hblpower" in q and "plc.a" in q:
            return LLMResponse(
                text=(
                    "HBLPOWER PLC.A completeness is COMPLETE: required PE ROE D/E sector "
                    "are present, subject to recorded conflicts [1]. This does not "
                    "authorize BUY or SELL."
                ),
                model="fake-chat",
                usage={"tokens": 24},
            )
        return LLMResponse(
            text="I don't have information about that in my knowledge base.",
            model="fake-chat",
            usage={"tokens": 8},
        )


def _write_store(tmp_path: Path, symbols: dict) -> Path:
    path = tmp_path / "investment" / "fundamentals" / "market_intelligence.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "version": "li.2.fundamentals",
        "program_id": "market_intelligence",
        "symbols": symbols,
    }
    path.write_text(json.dumps(doc), encoding="utf-8")
    return tmp_path


def _wired(tmp_path: Path, llm=None):
    svc, docs, chunks, embs = _service()
    llm = llm or KeywordEmbedLLM()
    svc._llm = llm
    findings = SummaryFindingRepo()
    femb = FakeFindingEmb()
    svc._findings = findings
    svc._finding_embeddings = femb
    data_dir = _write_store(
        tmp_path,
        {"HBLPOWER.NS": HBLPOWER_ROW, "TATACHEM.NS": TATACHEM_ROW},
    )
    return svc, docs, chunks, embs, findings, femb, llm, data_dir


def test_s4_1_deterministic_generation_no_llm():
    a = build_fundamental_summary(HBLPOWER_ROW)
    b = build_fundamental_summary(HBLPOWER_ROW)
    assert a["statement"] == b["statement"]
    assert a["fingerprint"] == b["fingerprint"]
    assert a["value"]["metrics"]["pe"]["display"] == "25.86"
    tree = ast.parse(
        (ROOT / "atlas" / "investment" / "fundamental_summary.py").read_text(
            encoding="utf-8"
        )
    )
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert "ollama" not in imported
    assert not any(name.startswith("atlas.llm") for name in imported)


def test_s4_2_every_metric_has_canonical_provenance():
    summary = build_fundamental_summary(HBLPOWER_ROW)
    for field in ("pe", "roe", "debt_to_equity", "fcf"):
        m = summary["value"]["metrics"][field]
        assert m["source"] == "nse_xbrl"
        assert m["calculation_id"]
        assert m["raw_evidence_id"] == HBLPOWER_ROW["nse_raw_evidence_id"]
    assert summary["value"]["canonical_filing_id"] == HBLPOWER_ROW["nse_raw_evidence_id"]
    assert summary["value"]["evidence_as_of"] == "2026-09-19T02:53:05Z"
    assert summary["value"]["fundamental_as_of"] == "2026-09-18"
    assert summary["value"]["metrics"]["debt_to_equity"]["definition_id"] == DEBT_DEFINITION_ID


def test_s4_3_valid_unknown_conflict_independently():
    valid = build_fundamental_summary(CLEAN_ROW)
    assert valid["value"]["knowledge_status"] == "VALID"
    assert valid["value"]["metrics"]["pe"]["status"] == "VALID"
    assert valid["value"]["plc_a_state"] == "COMPLETE"
    assert valid["value"]["conflicts"] == []

    unknown = build_fundamental_summary(TATACHEM_ROW)
    pe = unknown["value"]["metrics"]["pe"]
    assert pe["status"] == "UNKNOWN"
    assert pe["value"] is None
    assert pe["reason"] == "non_positive_eps"
    assert pe["stale_invalid"] == -3.99
    assert "PE is UNKNOWN" in unknown["statement"]
    assert "-3.99" in unknown["statement"]
    assert "is not 0" in unknown["statement"]
    assert unknown["value"]["plc_a_state"] == "INCOMPLETE"
    assert "PE_UNKNOWN" in str(unknown["value"]["plc_a_blocking_reason"])

    conflict = build_fundamental_summary(HBLPOWER_ROW)
    assert conflict["value"]["knowledge_status"] == "CONFLICT"
    assert conflict["value"]["metrics"]["pe"]["status"] == "CONFLICT"
    assert conflict["value"]["metrics"]["pe"]["value"] == HBLPOWER_ROW["pe"]
    types = {c["conflict_type"] for c in conflict["value"]["conflicts"]}
    assert "PE_EVIDENCE" in types
    assert "DEBT_DEFINITION" in types
    assert "93.72" in conflict["statement"]
    assert "25.86" in conflict["statement"]
    assert "do not silently choose a winner" in conflict["statement"]


def test_s4_pe_zero_is_unknown_not_usable():
    row = dict(CLEAN_ROW)
    row["pe"] = 0
    summary = build_fundamental_summary(row)
    assert summary["value"]["metrics"]["pe"]["status"] == "UNKNOWN"
    assert summary["value"]["metrics"]["pe"]["value"] is None
    assert summary["value"]["metrics"]["pe"]["display"] == "UNKNOWN"


def test_s4_identity_keys_do_not_collide():
    h = build_fundamental_summary(HBLPOWER_ROW)
    t = build_fundamental_summary(TATACHEM_ROW)
    hk = finding_identity_key(
        {"claim_type": CLAIM_TYPE, "domain": "research", "value": h["value"]}
    )
    tk = finding_identity_key(
        {"claim_type": CLAIM_TYPE, "domain": "research", "value": t["value"]}
    )
    assert hk != tk
    assert hk[0] == "fundamental_summary"
    assert "HBLPOWER" in hk[2]


def test_s4_4_and_s4_5_embed_and_retrieve(tmp_path: Path):
    svc, _docs, chunks, embs, findings, femb, _llm, data_dir = _wired(tmp_path)
    n_chunks = sum(len(v) for v in chunks.by_doc.values())
    n_chunk_vecs = len(embs.vectors)
    out = run_tick(svc, str(data_dir))
    assert out["ok"] is True
    assert out["llm_not_used"] is True
    assert tuple(out["symbols"]) == DEFAULT_SLICE_SYMBOLS
    assert len(femb.vectors) == 2
    assert all(model == "fake-embed" for (_fid, model) in femb.vectors)
    assert sum(len(v) for v in chunks.by_doc.values()) == n_chunks
    assert len(embs.vectors) == n_chunk_vecs

    hbl = svc.retrieve(
        "Why did HBLPOWER pass PLC.A?", k=5, role="research", mode="hybrid"
    )
    assert any(h.tier == TIER_FINDINGS and "HBLPOWER" in h.content for h in hbl.hits)
    assert any("PLC.A completeness COMPLETE" in h.content for h in hbl.hits)

    tata = svc.retrieve(
        "Why is TATACHEM still blocked?", k=5, role="research", mode="hybrid"
    )
    assert any(h.tier == TIER_FINDINGS and "TATACHEM" in h.content for h in tata.hits)
    assert any("still blocked" in h.content for h in tata.hits)

    again = run_tick(svc, str(data_dir))
    assert all(r["action"] == "unchanged" for r in again["results"])
    assert len([r for r in findings.rows if r["status"] == "active"]) == 2


def test_s4_new_filing_supersedes_old_finding(tmp_path: Path):
    svc, _docs, _chunks, _embs, findings, femb, _llm, data_dir = _wired(tmp_path)
    first = publish_symbol(svc, str(data_dir), "HBLPOWER.NS")
    assert first["action"] == "created"
    store = json.loads(
        (data_dir / "investment" / "fundamentals" / "market_intelligence.json").read_text()
    )
    store["symbols"]["HBLPOWER.NS"] = {
        **HBLPOWER_ROW,
        "pe": 26.1,
        "nse_raw_evidence_id": "new-filing-id",
        "evidence": {
            **HBLPOWER_ROW["evidence"],
            "pe": [
                {
                    "as_of": "2026-09-20",
                    "recorded_at": "2026-09-20T00:00:00Z",
                    "source": "nse_xbrl",
                    "value": 26.1,
                }
            ],
        },
        "evidence_conflicts": [
            {
                "conflict_type": "DEBT_DEFINITION",
                "field": "debt_to_equity",
                "note": "IFIndAs BorrowingsCurrent/Noncurrent may include Ind AS 116 lease liabilities.",
            }
        ],
    }
    (data_dir / "investment" / "fundamentals" / "market_intelligence.json").write_text(
        json.dumps(store)
    )
    second = publish_symbol(svc, str(data_dir), "HBLPOWER.NS")
    assert second["action"] == "superseded"
    assert second["finding_id"] != first["finding_id"]
    old = next(r for r in findings.rows if r["id"] == first["finding_id"])
    assert old["status"] == "superseded"
    assert femb.meta[first["finding_id"]]["status"] == "superseded"


def test_s4_6_s4_7_s4_8_llm_explains_retrieved_summary(tmp_path: Path):
    llm = GroundedLLM()
    svc, _docs, _chunks, _embs, _findings, _femb, _wired_llm, data_dir = _wired(
        tmp_path, llm=llm
    )
    assert run_tick(svc, str(data_dir))["ok"] is True
    agent = RagAgent(svc, llm, None, similarity_floor=0.0)

    hbl = agent.run(
        "Why did HBLPOWER pass PLC.A?", role="research", similarity_floor=0.0, k=5
    )
    assert "COMPLETE" in hbl.answer
    assert "not authorize" in hbl.answer.lower()
    assert any(str(getattr(c, "chunk_id", "")).startswith("finding:") for c in hbl.citations)
    assert "HBLPOWER" in (hbl.citations[0].snippet if hbl.citations else "")

    tata = agent.run(
        "What is TATACHEM's PE?", role="research", similarity_floor=0.0, k=5
    )
    assert "UNKNOWN" in tata.answer
    assert "non-positive" in tata.answer.lower() or "non_positive_eps" in tata.answer.lower()
    assert "-3.99" in tata.answer
    assert "not 0" in tata.answer

    conflicts = agent.run(
        "What conflicts exist for HBLPOWER?", role="research", similarity_floor=0.0, k=5
    )
    assert "93.72" in conflicts.answer
    assert "25.86" in conflicts.answer
    assert "DEBT_DEFINITION" in conflicts.answer
    assert llm.calls == 3
