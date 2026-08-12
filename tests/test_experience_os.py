"""Experience OS journal shape (EX.1 / OI-MP1)."""

from __future__ import annotations

from atlas.experience import ExperienceOS, journal_from_row, parse_journal_text


class _Learning:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    def remember_experience(self, **fields):
        row = {
            "id": f"e{len(self.rows) + 1}",
            "title": fields.get("title"),
            "problem": fields.get("problem"),
            "solution": fields.get("solution"),
            "lessons": fields.get("lessons"),
            "domain": fields.get("domain"),
            "tags": list(fields.get("tags") or []),
            "payload": {
                k: v
                for k, v in fields.items()
                if k
                not in {
                    "title",
                    "problem",
                    "solution",
                    "lessons",
                    "domain",
                    "tags",
                    "policy",
                }
            },
        }
        # Mirror LearningService.apply: full fields land in payload
        row["payload"] = dict(fields)
        self.rows.append(row)
        return {"applied": True, "id": row["id"]}

    def list_experiences(self, *, limit=50):
        return list(self.rows)[:limit]

    def recall(self, query, *, limit=None):
        q = (query or "").lower()
        hits = [
            r
            for r in self.rows
            if q in str(r.get("title") or "").lower()
            or q in str(r.get("problem") or "").lower()
            or q in str(r.get("lessons") or "").lower()
        ]
        return hits[: (limit or 5)]

    def advice_for(self, query, *, limit=None):
        hits = self.recall(query, limit=limit)
        return {
            "query": query,
            "count": len(hits),
            "advice": "\n".join(f"- {h.get('title')}" for h in hits),
            "experiences": hits,
            "mutating": False,
        }


def test_shape():
    eos = ExperienceOS(_Learning())
    s = eos.shape()
    assert s["steps"][0] == "observation"
    assert s["steps"][-1] == "lesson"
    assert s["version"] == "ex.2-self0"
    assert "learning_loop" in s
    assert "affected_beliefs" in s["learning_loop"]


def test_journal_strict_and_store():
    learn = _Learning()
    eos = ExperienceOS(learn)
    bad = eos.journal(
        title="x",
        observation="rsi low",
        decision="",
        outcome="loss",
        reflection="missed earnings",
        lesson="check calendar",
    )
    assert bad["ok"] is False
    assert "decision" in bad["missing"]

    ok = eos.journal(
        title="Tata Motors exit",
        observation="RSI oversold; price below 200 DMA",
        reasoning="Mean-reversion within risk limits",
        decision="Buy (sim)",
        outcome="-6%",
        reflection="Ignored earnings tomorrow",
        lesson="Always check earnings calendar before entry",
        domain="markets",
        tags=["tata", "paper_trading"],
    )
    assert ok["ok"] is True
    assert len(learn.rows) == 1
    assert learn.rows[0]["payload"]["journal"]["lesson"].startswith("Always check")
    assert "experience_journal" in learn.rows[0]["tags"]


def test_parse_and_recall_structured():
    text = (
        "Observation: RSI=28\n"
        "Reasoning: oversold\n"
        "Decision: sell DEMO (simulation)\n"
        "Outcome: loss -12.5\n"
        "Reflection: contradicted thesis\n"
        "Lesson: re-check catalysts"
    )
    parsed = parse_journal_text(text)
    assert parsed["observation"] == "RSI=28"
    assert parsed["lesson"] == "re-check catalysts"

    learn = _Learning()
    eos = ExperienceOS(learn)
    eos.journal(
        title="closed DEMO",
        observation="RSI=28",
        decision="sell DEMO",
        outcome="loss",
        reflection="bad",
        lesson="check catalysts",
        domain="markets",
        tags=["demo"],
    )
    journals = eos.recall("DEMO", limit=5)
    assert journals
    assert journals[0]["complete"] is True
    assert journals[0]["journal"]["lesson"] == "check catalysts"


def test_journal_from_legacy_row():
    row = {
        "id": "e1",
        "title": "legacy",
        "problem": "Observation: vol spike\nDecision: watch\nOutcome: flat",
        "solution": "Reflection: noise",
        "lessons": "Lesson: wait for confirmation",
        "tags": [],
        "payload": {},
    }
    j = journal_from_row(row)
    assert j["journal"]["observation"] == "vol spike"
    assert j["journal"]["lesson"] == "wait for confirmation"
    assert j["complete"] is True
