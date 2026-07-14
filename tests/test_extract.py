"""Tests for Claim Extraction (Stage 3, Step 4 / §5f, C2 / D3.1)."""

from __future__ import annotations

from atlas.evidence.models import LEVEL_PEER_REVIEWED
from atlas.llm.provider import LLMResponse
from atlas.research.extract import ClaimExtractor
from atlas.research.reader import Reader

_PAPER = """Abstract
We measured a soiling loss of 0.35 %/day on PV modules in a desert climate.

4. Results
The proposed CNN model reduced the RMSE from 3.1% to 1.2% versus the baseline.
The dataset was collected in 2021 across many sites.

Conclusion
Data-driven cleaning reduced operational cost by 18 percent.
"""


class _RoleStub:
    def __init__(self, text, raises=False):
        self._text = text
        self._raises = raises

    def chat(self, messages, **options):
        if self._raises:
            raise RuntimeError("llm down")
        return LLMResponse(text=self._text, model="fake")


class FakeLLM:
    def __init__(self, text="", raises=False):
        self._text = text
        self._raises = raises
        self.roles = []

    def for_role(self, role):
        self.roles.append(role)
        return _RoleStub(self._text, self._raises)


def _doc():
    return Reader().read_text(_PAPER, source_id="ieee:1", title="Soiling paper",
                              url="https://ieeexplore.ieee.org/document/1")


def test_numeric_claims_extracted_deterministically():
    result = ClaimExtractor().extract(_doc(), evidence_level=LEVEL_PEER_REVIEWED)
    assert result.numeric >= 3
    statements = [c.statement for c in result.claims]
    assert any("0.35" in s for s in statements)
    assert any("1.2%" in s or "1.2 %" in s or "RMSE" in s for s in statements)
    assert any("18 percent" in s for s in statements)


def test_values_and_units_parsed():
    result = ClaimExtractor().extract(_doc(), evidence_level=LEVEL_PEER_REVIEWED)
    soiling = next(c for c in result.claims if "0.35" in c.statement)
    assert soiling.value is not None
    assert soiling.value.number == 0.35
    assert soiling.value.unit == "%"
    # a soiling-related kind is inferred from the sentence
    assert soiling.value.kind in ("soiling_loss", "loss")


def test_evidence_item_carries_source_and_locator():
    result = ClaimExtractor().extract(_doc(), evidence_level=LEVEL_PEER_REVIEWED)
    claim = result.claims[0]
    assert len(claim.evidence) == 1
    ev = claim.evidence[0]
    assert ev.source_id == "ieee:1"
    assert ev.evidence_level == LEVEL_PEER_REVIEWED
    assert ev.locator  # a section label was recorded


def test_bare_year_without_unit_is_not_a_claim():
    # "collected in 2021 across many sites" has a year but no unit → skipped.
    result = ClaimExtractor().extract(_doc())
    assert not any("collected in 2021 across" in c.statement and c.value and c.value.number == 2021
                   for c in result.claims)


def test_cap_limits_claims_per_doc():
    many = "Results\n" + " ".join(f"Metric {i} was {i}.5% higher." for i in range(30))
    doc = Reader().read_text(many, source_id="s1")
    result = ClaimExtractor(max_claims_per_doc=5).extract(doc)
    assert result.count == 5


def test_dedup_identical_statements():
    text = "Results\nThe loss was 2.0%.\nThe loss was 2.0%.\n"
    doc = Reader().read_text(text, source_id="s1")
    result = ClaimExtractor().extract(doc)
    assert result.count == 1


def test_llm_prose_claims_added_and_capped():
    payload = """[
      {"statement": "Data-driven cleaning improves ROI in arid climates.",
       "value": null, "locator": "conclusion"},
      {"statement": "Soiling is climate dependent.", "value": {"number": 0, "unit": "", "kind": ""},
       "locator": "abstract"}
    ]"""
    llm = FakeLLM(text=payload)
    result = ClaimExtractor(llm=llm).extract(_doc(), evidence_level=LEVEL_PEER_REVIEWED)
    assert result.prose == 2
    assert "researcher" in llm.roles  # used the researcher role (A5)
    assert any("ROI in arid" in c.statement for c in result.claims)


def test_llm_failure_degrades_to_deterministic():
    llm = FakeLLM(raises=True)
    result = ClaimExtractor(llm=llm).extract(_doc())
    assert result.prose == 0
    assert result.numeric >= 3  # deterministic claims still produced


def test_llm_garbage_is_ignored():
    result = ClaimExtractor(llm=FakeLLM(text="not json")).extract(_doc())
    assert result.prose == 0


def test_empty_document_yields_nothing():
    doc = Reader().read_text("", source_id="s1")
    assert ClaimExtractor().extract(doc).count == 0
