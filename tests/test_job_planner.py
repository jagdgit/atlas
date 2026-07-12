"""Tests for JobPlanner decomposition (S12, D2c)."""

from __future__ import annotations

from atlas.jobs.planner import DecomposedStep, JobPlanner
from atlas.llm.provider import LLMResponse
from atlas.planner.planner import Intent


class _RoleStub:
    def __init__(self, text):
        self._text = text

    def chat(self, messages, **options):
        return LLMResponse(text=self._text, model="fake")


class FakeLLM:
    def __init__(self, text):
        self._text = text

    def for_role(self, role):
        assert role == "planner"
        return _RoleStub(self._text)


def test_deterministic_fallback_without_llm():
    steps = JobPlanner().decompose("What is 12 times 8?")
    assert len(steps) == 1
    assert isinstance(steps[0], DecomposedStep)
    assert steps[0].intent == Intent.REACT


def test_empty_objective_yields_react_step():
    steps = JobPlanner().decompose("   ")
    assert steps[0].intent == Intent.REACT


def test_llm_multistep_decomposition_parsed_and_validated():
    payload = """[
      {"intent": "web_fetch", "capability": "web", "args": {"url": "https://x"},
       "description": "fetch", "depends_on": null},
      {"intent": "ask_knowledge", "capability": "knowledge", "args": {},
       "description": "answer", "depends_on": 0}
    ]"""
    steps = JobPlanner(llm=FakeLLM(payload)).decompose("research soiling loss")
    assert [s.intent for s in steps] == [Intent.WEB_FETCH, Intent.ASK_KNOWLEDGE]
    assert steps[1].depends_on == 0
    assert steps[0].args == {"url": "https://x"}


def test_llm_garbage_falls_back_to_deterministic():
    steps = JobPlanner(llm=FakeLLM("not json at all")).decompose("hello there")
    # falls back to the deterministic single-step plan
    assert len(steps) == 1


def test_invalid_intents_dropped_and_bad_depends_clamped():
    payload = """[
      {"intent": "bogus", "capability": "web", "args": {}},
      {"intent": "react", "capability": "nope", "args": {}, "depends_on": 5}
    ]"""
    steps = JobPlanner(llm=FakeLLM(payload)).decompose("do a thing")
    # only the react step survives; unknown capability coerced to 'agent';
    # out-of-range depends_on clamped to None
    assert len(steps) == 1
    assert steps[0].intent == Intent.REACT
    assert steps[0].capability == "agent"
    assert steps[0].depends_on is None


def test_max_steps_caps_decomposition():
    items = ",".join(
        '{"intent": "react", "capability": "agent", "args": {}}' for _ in range(10)
    )
    steps = JobPlanner(llm=FakeLLM(f"[{items}]"), max_steps=3).decompose("many")
    assert len(steps) == 3


def test_research_first_coerces_bare_react_to_research():
    # A bare noun-phrase objective would otherwise fall to a lone react step; with
    # research_first it becomes a research step so the job gathers real evidence.
    steps = JobPlanner(research_first=True).decompose("Data-driven soiling estimation")
    assert len(steps) == 1
    assert steps[0].intent == Intent.RESEARCH
    assert steps[0].capability == "research"
    assert steps[0].args == {"objective": "Data-driven soiling estimation"}


def test_research_first_leaves_multistep_plans_untouched():
    payload = """[
      {"intent": "web_search", "capability": "search", "args": {"query": "x"}},
      {"intent": "research", "capability": "research", "args": {"objective": "x"}, "depends_on": 0}
    ]"""
    steps = JobPlanner(llm=FakeLLM(payload), research_first=True).decompose("x")
    assert [s.intent for s in steps] == [Intent.WEB_SEARCH, Intent.RESEARCH]


def test_research_first_off_keeps_bare_react():
    steps = JobPlanner(research_first=False).decompose("Data-driven soiling estimation")
    assert len(steps) == 1
    assert steps[0].intent == Intent.REACT
