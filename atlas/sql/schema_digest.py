"""Resolve real table schemas for the planner prompt (J5).

Why this exists: the job planner was told, in hand-written prose, that
``scheduler.task_runs`` has ``task_id, status, error, started_at, worker_id`` and
``scheduler.tasks`` has ``task_type, status, last_error``. The model merged the two
lists and planned ``SELECT task_id, task_type, ... FROM scheduler.task_runs``, which
Postgres rejected with ``column "task_type" does not exist``. A 111-second plan was
wasted on a column that could have been looked up in 40 milliseconds.

So the planner stops guessing. The schema is a fact Atlas can read; reading it costs
one cheap catalog query, while letting the model invent it costs a full planning round
trip per mistake. On CPU-only hardware that trade is not close — every token the model
does not have to invent is a token that cannot be wrong.

Selection is deliberately deterministic (token overlap, no LLM call) and the digest is
hard-capped, because prompt tokens are the binding resource: dumping all 70 tables
would cost more than the mistake it prevents.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Protocol

# Prompt budget. ~1.8 KB of schema and sample values is a few hundred tokens —
# affordable next to a plan that costs ~233 tokens to emit, and far cheaper than one
# wrong-column or wrong-literal retry at ~160 s each.
_MAX_CHARS = 1800
_MAX_TABLES = 8
_MAX_COLUMNS = 24
_MIN_TOKEN_LEN = 3

# J6 — value grounding. With real columns in the prompt the model stopped inventing
# schema and started inventing *data*: it wrote
# ``error LIKE '%JSON serialization error%'`` against a column whose actual text is
# ``Object of type set is not JSON serializable``. Valid SQL, zero rows. So the same
# treatment applies one level down — a short sample of the values that actually occur
# in the low-cardinality columns an objective is about.
_VALUE_COLUMNS = frozenset(
    {
        "status", "state", "outcome", "task_type", "type", "kind", "level", "module",
        "error", "message", "reason", "side", "symbol", "program", "source", "phase",
    }
)
_MAX_VALUE_COLUMNS = 2          # per table
_MAX_VALUES = 6                 # per column
_VALUE_CHARS = 90               # per value
_VALUE_SCAN_ROWS = 20000        # bounded scan: never a full-table DISTINCT

# A bounded scan without ordering returns whichever rows the planner reaches first,
# which are the *oldest*. Measured consequence: sampling `scheduler.task_runs.error`
# returned only the long-standing "no handler registered" errors, so the model never
# saw today's "Object of type set is not JSON serializable" and kept guessing the
# literal. Recent rows are what an objective about "today" is asking about.
_RECENCY_COLUMNS = (
    "finished_at", "completed_at", "started_at", "created_at", "updated_at", "occurred_at",
)
_VALUE_WINDOW_DAYS = 7

# Value sampling costs ~12 s on `scheduler.task_runs`: it holds 35 million rows with no
# index on `error`, so finding non-NULL errors is a sequential scan either way. Value
# distributions change slowly, so this is cached rather than made cleverer — a cache is
# the honest fix when the query is unavoidably expensive and the answer is stable.
_VALUE_CACHE_TTL = 900.0
_VALUE_CACHE_MAX = 64
_value_cache: dict[tuple[str, str, str], tuple[float, list[str]]] = {}

_WORD = re.compile(r"[a-z0-9_]+")

# Words that match half the catalog and so carry no selection signal.
_STOPWORDS = frozenset(
    {
        "the", "and", "for", "with", "from", "that", "this", "atlas", "all", "any",
        "its", "was", "why", "how", "what", "when", "use", "using", "find", "state",
        "your", "you", "today", "root", "cause", "verify", "conclusion", "local",
        "data", "database", "table", "tables", "query", "report", "check", "look",
        "investigate", "identify", "determine", "analyse", "analyze", "recent",
    }
)


class _SchemaSource(Protocol):
    def tables(self, source: str | None = ...) -> dict[str, Any]: ...
    def schema(self, table: str, source: str | None = ...) -> dict[str, Any]: ...
    def query(self, sql: str, *, source: str | None = ..., **kwargs: Any) -> dict[str, Any]: ...


_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _is_safe_relation(table: str) -> bool:
    """Only plain ``[schema.]table`` identifiers are interpolated into the probe."""
    parts = table.split(".")
    return len(parts) in (1, 2) and all(_IDENT.match(p) for p in parts)


def _tokens(text: str) -> set[str]:
    words = {w for w in _WORD.findall((text or "").lower()) if len(w) >= _MIN_TOKEN_LEN}
    words -= _STOPWORDS
    # Crude depluralisation so "tasks"/"failures" match `task_runs`/`failure`.
    return words | {w[:-1] for w in words if w.endswith("s") and len(w) > _MIN_TOKEN_LEN}


def _score(table: str, wanted: set[str]) -> int:
    """How many distinct objective words appear in this qualified table name."""
    parts = {p for p in _WORD.findall(table.lower()) if p}
    parts |= {p for part in parts for p in part.split("_")}
    return len(parts & wanted)


def _sample_values(
    client: _SchemaSource,
    table: str,
    column: str,
    source: str,
    log: logging.Logger,
    recency: str | None = None,
) -> list[str]:
    """Most common values of one column, bounded, truncated and redacted.

    Bounded by a subquery rather than ``DISTINCT`` over the whole relation:
    ``decision.decisions`` has 45,765 rows and ``activity.activity_events`` 41,679, and
    a planner prompt must not be able to start an expensive scan on the live database.

    Redacted with the log redactor because these values are free text that goes
    straight into an LLM prompt — the one path where an accidentally logged credential
    would leave the machine.
    """
    if not _is_safe_relation(table) or not _IDENT.match(column):
        return []
    import time

    key = (source, table, column)
    cached = _value_cache.get(key)
    now = time.monotonic()
    if cached is not None and now - cached[0] < _VALUE_CACHE_TTL:
        return list(cached[1])

    from atlas.plugins.logs_plugin import redact

    def _probe(where: str) -> list[str]:
        sql = (
            f"SELECT left({column}::text, {_VALUE_CHARS}) AS v, count(*) AS n "
            f"FROM (SELECT {column} FROM {table} WHERE {column} IS NOT NULL{where} "
            f"LIMIT {_VALUE_SCAN_ROWS}) s "
            f"GROUP BY 1 ORDER BY n DESC, 1 LIMIT {_MAX_VALUES}"
        )
        try:
            out = client.query(sql, source=source)
        except Exception:  # noqa: BLE001 - grounding never fails planning
            log.debug("value sample failed for %s.%s", table, column, exc_info=True)
            return []
        if not isinstance(out, dict) or out.get("outcome") != "ok":
            return []
        found: list[str] = []
        for row in out.get("rows") or []:
            raw = row[0] if isinstance(row, (list, tuple)) else (row or {}).get("v")
            text = redact(str(raw)).strip()
            if text:
                found.append(text)
        return found

    # A recency *window* rather than ``ORDER BY ... DESC``: sorting the whole relation
    # cost 27.8 s on ``scheduler.task_runs`` where the window costs well under a second,
    # and an index on the timestamp makes the window cheaper still. Falls back to an
    # unordered sample when the window is empty, so a quiet table still grounds.
    values: list[str] = []
    if recency and _IDENT.match(recency):
        values = _probe(f" AND {recency} >= now() - interval '{_VALUE_WINDOW_DAYS} days'")
    if not values:
        values = _probe("")
    # Only successes are cached. A failed probe and a genuinely empty column are
    # indistinguishable here, so caching the empty result would pin a transient
    # database hiccup into the planner prompt for the next 15 minutes.
    if values:
        if len(_value_cache) >= _VALUE_CACHE_MAX:
            _value_cache.clear()
        _value_cache[key] = (now, list(values))
    return values


def clear_value_cache() -> None:
    """Drop cached value samples (tests, and after a schema change)."""
    _value_cache.clear()


def build_digest(
    client: _SchemaSource | None,
    objective: str,
    *,
    source: str = "atlas",
    max_tables: int = _MAX_TABLES,
    max_columns: int = _MAX_COLUMNS,
    max_chars: int = _MAX_CHARS,
    with_values: bool = True,
    logger: logging.Logger | None = None,
) -> str:
    """Return a compact ``schema.table(col, col, ...)`` digest, or ``""``.

    Empty when there is no client, the catalog is unreachable, or no table name
    overlaps the objective — an empty digest leaves the prompt exactly as it was, so
    this can never make planning worse than not having it.
    """
    log = logger or logging.getLogger("atlas.sql.schema_digest")
    if client is None:
        return ""
    wanted = _tokens(objective)
    if not wanted:
        return ""
    try:
        listing = client.tables(source=source)
    except Exception:  # noqa: BLE001 - grounding is an optimisation, never a failure
        log.debug("schema digest: table listing failed", exc_info=True)
        return ""
    if not isinstance(listing, dict) or listing.get("outcome") != "ok":
        log.debug("schema digest: table listing unavailable (%s)", (listing or {}).get("reason"))
        return ""

    names = [str(t) for t in (listing.get("tables") or [])]
    ranked = sorted(
        ((_score(n, wanted), n) for n in names),
        key=lambda pair: (-pair[0], pair[1]),
    )
    picked = [name for score, name in ranked if score > 0][:max_tables]
    if not picked:
        return ""

    lines: list[str] = []
    used = 0
    for table in picked:
        try:
            info = client.schema(table, source=source)
        except Exception:  # noqa: BLE001
            log.debug("schema digest: schema lookup failed for %s", table, exc_info=True)
            continue
        if not isinstance(info, dict) or info.get("outcome") != "ok":
            continue
        cols = info.get("columns") or []
        # Secret-looking columns are named but never offered for selection: the planner
        # should know they exist and know not to read them.
        visible = [str(c.get("name")) for c in cols if not c.get("secret")][:max_columns]
        if not visible:
            continue
        line = f"{table}({', '.join(visible)})"
        if used + len(line) + 1 > max_chars:
            break
        lines.append(line)
        used += len(line) + 1

        if not with_values:
            continue
        # Sample only columns the objective actually asks about, so an objective about
        # errors gets error text and one about symbols gets symbols.
        probes = [
            c for c in visible
            if c in _VALUE_COLUMNS and (set(c.split("_")) & wanted or c in wanted)
        ][:_MAX_VALUE_COLUMNS]
        all_names = [str(c.get("name")) for c in cols]
        recency = next((c for c in _RECENCY_COLUMNS if c in all_names), None)
        for column in probes:
            values = _sample_values(client, table, column, source, log, recency=recency)
            if not values:
                continue
            rendered = "; ".join(values)
            vline = f"  {table}.{column} actual values: {rendered}"
            if used + len(vline) + 1 > max_chars:
                break
            lines.append(vline)
            used += len(vline) + 1
    return "\n".join(lines)
