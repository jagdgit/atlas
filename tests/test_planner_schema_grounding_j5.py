"""J5 — the planner resolves real column names instead of recalling them.

Covers the two defects measured against the live model on 2026-10-06:
  1. a hand-written prose schema hint let ``qwen3:4b`` merge the columns of two
     scheduler tables and emit ``task_type`` on ``scheduler.task_runs``; and
  2. with a resolved schema in the prompt the SQL became correct but the steps were
     labelled ``recall``, so the queries would never have been executed.
"""

from __future__ import annotations

import pytest

from atlas.jobs.planner import JobPlanner
from atlas.planner.planner import Intent
from atlas.sql.schema_digest import build_digest, clear_value_cache


@pytest.fixture(autouse=True)
def _clean_value_cache():
    """Value samples are cached process-wide; keep tests independent of each other."""
    clear_value_cache()
    yield
    clear_value_cache()

TABLES = [
    "scheduler.task_runs",
    "scheduler.tasks",
    "audit.logs",
    "sim.trades",
    "knowledge.chunks",
]
COLUMNS = {
    "scheduler.task_runs": ["id", "task_id", "status", "started_at", "error", "worker_id"],
    "scheduler.tasks": ["id", "task_type", "payload", "status", "last_error"],
    "audit.logs": ["id", "level", "module", "message", "created_at"],
    "sim.trades": ["id", "symbol", "side", "qty", "price"],
    "knowledge.chunks": ["id", "document_id", "text", "token_count"],
}


class FakeSQL:
    """Minimal stand-in for ``SQLPlugin`` (same dict-with-``outcome`` contract)."""

    name = "sql"

    def __init__(self, *, tables=None, columns=None, fail=False, secret=()):
        self._tables = TABLES if tables is None else tables
        self._columns = COLUMNS if columns is None else columns
        self._fail = fail
        self._secret = set(secret)
        self.calls: list[str] = []

    def tables(self, source=None):
        if self._fail:
            return {"outcome": "unavailable", "reason": "down"}
        return {"outcome": "ok", "tables": list(self._tables)}

    def schema(self, table, source=None):
        self.calls.append(table)
        cols = self._columns.get(table)
        if cols is None:
            return {"outcome": "error", "reason": "no such table"}
        return {
            "outcome": "ok",
            "columns": [{"name": c, "secret": c in self._secret} for c in cols],
        }


# --- digest selection -------------------------------------------------------


def test_digest_picks_tables_the_objective_mentions():
    digest = build_digest(FakeSQL(), "why did the scheduler fail tasks with an error")
    assert "scheduler.task_runs(" in digest
    assert "scheduler.tasks(" in digest
    assert "sim.trades" not in digest


def test_digest_lists_the_real_columns_and_nothing_else():
    digest = build_digest(FakeSQL(), "scheduler task_runs failures")
    line = next(ln for ln in digest.splitlines() if ln.startswith("scheduler.task_runs("))
    listed = line[len("scheduler.task_runs(") : -1].split(", ")
    assert listed == COLUMNS["scheduler.task_runs"]
    # The exact hallucination this exists to prevent.
    assert "task_type" not in listed


def test_digest_is_empty_for_an_unrelated_objective():
    assert build_digest(FakeSQL(), "what is the capital of France") == ""


def test_digest_is_empty_without_a_client():
    assert build_digest(None, "scheduler tasks") == ""


def test_digest_is_empty_when_the_catalog_is_unreachable():
    assert build_digest(FakeSQL(fail=True), "scheduler tasks") == ""


def test_digest_survives_a_raising_client():
    class Boom(FakeSQL):
        def tables(self, source=None):
            raise RuntimeError("nope")

    assert build_digest(Boom(), "scheduler tasks") == ""


def test_digest_skips_a_table_whose_schema_lookup_fails():
    client = FakeSQL(tables=[*TABLES, "scheduler.ghost"])
    digest = build_digest(client, "scheduler tasks ghost")
    assert "scheduler.ghost" not in digest
    assert "scheduler.tasks(" in digest


def test_digest_omits_secret_columns_from_selection():
    client = FakeSQL(secret={"payload"})
    digest = build_digest(client, "scheduler tasks payload")
    line = next(ln for ln in digest.splitlines() if ln.startswith("scheduler.tasks("))
    assert "payload" not in line
    assert "task_type" in line


def test_digest_respects_the_prompt_budget():
    # Prompt tokens are the binding resource; an unbounded digest costs more than the
    # mistake it prevents.
    wide = {f"ops.table_{i}": [f"col_{j}" for j in range(30)] for i in range(20)}
    client = FakeSQL(tables=list(wide), columns=wide)
    digest = build_digest(client, " ".join(wide), max_chars=300)
    assert 0 < len(digest) <= 300


def test_digest_caps_table_count():
    client = FakeSQL()
    digest = build_digest(client, "scheduler tasks runs logs trades chunks", max_tables=2)
    assert len(digest.splitlines()) <= 2


# --- prompt wiring ----------------------------------------------------------


class RecordingLLM:
    """Captures the system prompt and returns a canned plan."""

    def __init__(self, payload: str):
        self._payload = payload
        self.system: str = ""

    def for_role(self, role):  # noqa: D102 - test double
        return self

    def chat(self, messages, **kwargs):
        self.system = messages[0].content

        class _Resp:
            text = self._payload

        return _Resp()


def _plan(payload: str, *, schema_source=None):
    llm = RecordingLLM(payload)
    planner = JobPlanner(llm=llm, max_steps=6, research_first=False)
    if schema_source is not None:
        planner.bind_schema_source(schema_source)
    steps = planner.decompose("why did the scheduler fail tasks with an error")
    return steps, llm


def test_resolved_schema_reaches_the_system_prompt():
    payload = '{"steps":[{"intent":"sql_query","capability":"sql","description":"x","args":{"sql":"SELECT 1"}}]}'
    _, llm = _plan(payload, schema_source=FakeSQL())
    assert "scheduler.task_runs(id, task_id, status, started_at, error, worker_id)" in llm.system


def test_prompt_no_longer_carries_a_hand_written_schema():
    payload = '{"steps":[{"intent":"react","capability":"agent","description":"x","args":{"query":"q"}}]}'
    _, llm = _plan(payload)
    # The merged-columns hint that caused the bad query must be gone for good.
    assert "task_type, status, last_error" not in llm.system


def test_planning_proceeds_when_grounding_is_unavailable():
    payload = '{"steps":[{"intent":"sql_query","capability":"sql","description":"x","args":{"sql":"SELECT 1"}}]}'
    steps, llm = _plan(payload, schema_source=FakeSQL(fail=True))
    assert len(steps) == 1
    assert steps[0].intent == Intent.SQL_QUERY
    assert "resolved just now" not in llm.system


# --- intent repair ----------------------------------------------------------


def test_sql_in_a_recall_step_is_rerouted_to_sql_query():
    # The live failure: correct SQL labelled `recall`, so it would never have run.
    payload = (
        '{"steps":[{"intent":"recall","capability":"memory","description":"x",'
        '"args":{"sql":"SELECT id FROM scheduler.task_runs","source":"atlas"}}]}'
    )
    steps, _ = _plan(payload, schema_source=FakeSQL())
    assert steps[0].intent == Intent.SQL_QUERY
    assert steps[0].capability == "sql"
    assert steps[0].args["sql"].startswith("SELECT id")


def test_code_in_a_mislabelled_step_is_rerouted_to_run_python():
    payload = (
        '{"steps":[{"intent":"recall","capability":"memory","description":"x",'
        '"args":{"code":"print(1)"}}]}'
    )
    steps, _ = _plan(payload, schema_source=FakeSQL())
    assert steps[0].intent == Intent.RUN_PYTHON
    assert steps[0].capability == "python"


@pytest.mark.parametrize("sql", ["", "   ", None, 42, {"a": 1}])
def test_a_non_sql_step_is_left_alone(sql):
    args = {"query": "q"} if sql is None else {"query": "q", "sql": sql}
    payload = {
        "steps": [
            {"intent": "recall", "capability": "memory", "description": "x", "args": args}
        ]
    }
    import json

    steps, _ = _plan(json.dumps(payload), schema_source=FakeSQL())
    assert steps[0].intent == Intent.RECALL


def test_a_correctly_labelled_sql_step_keeps_its_capability():
    payload = (
        '{"steps":[{"intent":"sql_query","capability":"sql","description":"x",'
        '"args":{"sql":"SELECT 1"}}]}'
    )
    steps, _ = _plan(payload, schema_source=FakeSQL())
    assert (steps[0].intent, steps[0].capability) == (Intent.SQL_QUERY, "sql")


# --- J6: value grounding ----------------------------------------------------


class ValueSQL(FakeSQL):
    """Adds the bounded value-sample probe `build_digest` issues."""

    def __init__(self, values=None, outcome="ok", **kw):
        super().__init__(**kw)
        self._values = values if values is not None else ["err A", "err B"]
        self._outcome = outcome
        self.queries: list[str] = []

    def query(self, sql, *, source=None, **kw):
        self.queries.append(sql)
        if self._outcome != "ok":
            return {"outcome": self._outcome, "reason": "nope"}
        return {"outcome": "ok", "columns": ["v", "n"],
                "rows": [(v, 1) for v in self._values]}


def test_actual_values_reach_the_digest():
    client = ValueSQL(values=["TypeError: Object of type set is not JSON serializable"])
    digest = build_digest(client, "scheduler task_runs error", source="atlas")
    assert "scheduler.task_runs.error actual values:" in digest
    assert "Object of type set is not JSON serializable" in digest


def test_values_are_only_sampled_for_columns_the_objective_mentions():
    client = ValueSQL()
    build_digest(client, "scheduler task_runs error", source="atlas")
    probed = [q for q in client.queries if "scheduler.task_runs" in q]
    assert probed, "expected a probe on the error column"
    assert all("error" in q for q in probed)
    assert not any("worker_id" in q for q in client.queries)


def test_value_probes_are_bounded_and_never_a_full_distinct():
    client = ValueSQL()
    build_digest(client, "scheduler task_runs error", source="atlas")
    probe = next(q for q in client.queries if "scheduler.task_runs" in q)
    assert "LIMIT 20000" in probe
    assert "DISTINCT" not in probe.upper()
    # Recent rows first: an objective about today must not be grounded on 2026-07 data.
    assert "interval '7 days'" in probe


def test_value_probes_are_redacted_before_entering_the_prompt():
    secret = "Authorization: Bearer abcdef1234567890abcdef"
    client = ValueSQL(values=[secret])
    digest = build_digest(client, "audit logs message", source="atlas")
    assert "abcdef1234567890abcdef" not in digest
    assert "[redacted]" in digest


def test_values_can_be_switched_off():
    client = ValueSQL()
    digest = build_digest(client, "scheduler task_runs error", with_values=False)
    assert "actual values" not in digest
    assert client.queries == []


def test_a_failing_value_probe_leaves_the_column_digest_intact():
    client = ValueSQL(outcome="error")
    digest = build_digest(client, "scheduler task_runs error", source="atlas")
    assert "scheduler.task_runs(" in digest
    assert "actual values" not in digest


def test_a_raising_value_probe_never_breaks_the_digest():
    class Boom(ValueSQL):
        def query(self, sql, *, source=None, **kw):
            raise RuntimeError("probe exploded")

    digest = build_digest(Boom(), "scheduler task_runs error", source="atlas")
    assert "scheduler.task_runs(" in digest


def test_value_samples_are_cached_so_planning_pays_once():
    client = ValueSQL()
    build_digest(client, "scheduler task_runs error", source="atlas")
    first = len(client.queries)
    assert first > 0, "expected a probe on the first call"
    build_digest(client, "scheduler task_runs error", source="atlas")
    assert len(client.queries) == first, "second digest should be served from cache"


def test_a_failed_probe_is_not_cached():
    # A transient failure must not pin an empty sample into the prompt for 15 minutes.
    boom = ValueSQL(outcome="error")
    build_digest(boom, "scheduler task_runs error", source="atlas")
    good = ValueSQL(values=["real error text"])
    digest = build_digest(good, "scheduler task_runs error", source="atlas")
    assert "real error text" in digest


def test_an_unsafe_relation_name_is_never_interpolated():
    from atlas.sql.schema_digest import _sample_values
    import logging

    client = ValueSQL()
    assert _sample_values(client, 'bad"; DROP TABLE x --', "error", "atlas", logging.getLogger()) == []
    assert _sample_values(client, "scheduler.task_runs", "col; --", "atlas", logging.getLogger()) == []
    assert client.queries == []
