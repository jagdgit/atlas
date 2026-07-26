"""Goal OS — durable objectives (OX.3) + progress narratives (OX.4).

A Goal is an **objective** first. Program and Portfolio are optional ways to
pursue it — not the Goal's identity.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from atlas.goals.progress import build_progress_report, format_progress_answer
from atlas.repositories.goal_repo import GOAL_STATUSES, InMemoryGoalRepository

_WORD = re.compile(r"[a-z0-9.+%-]+", re.I)


class GoalService:
    name = "goals"
    VERSION = "ox.4"

    def __init__(
        self,
        repo: Any | None = None,
        *,
        portfolio: Any | None = None,
        learning: Any | None = None,
        experience_os: Any | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._repo = repo if repo is not None else InMemoryGoalRepository()
        self._portfolio = portfolio
        self._learning = learning
        self._experience_os = experience_os
        self._logger = logger or logging.getLogger("atlas.goals")

    def bind(
        self,
        *,
        portfolio: Any | None = None,
        learning: Any | None = None,
        experience_os: Any | None = None,
    ) -> None:
        """Attach late-wired sources (bootstrap ordering)."""
        if portfolio is not None:
            self._portfolio = portfolio
        if learning is not None:
            self._learning = learning
        if experience_os is not None:
            self._experience_os = experience_os

    def create(
        self,
        title: str,
        *,
        objective: dict[str, Any] | str | None = None,
        success_criteria: dict[str, Any] | str | None = None,
        program_id: str | None = None,
        portfolio_key: str | None = None,
        portfolio_id: str | None = None,
        status: str = "active",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        title = (title or "").strip()
        if not title:
            raise ValueError("goal title / objective text is required")
        obj = _as_objective(objective, fallback_text=title)
        crit = _as_criteria(success_criteria)
        row = self._repo.create(
            title=title,
            objective=obj,
            status=status,
            success_criteria=crit,
            program_id=(program_id or None),
            portfolio_key=(portfolio_key or None),
            portfolio_id=(portfolio_id or None),
            progress={
                "phase": "learning",
                "note": "Goal created — ask for progress anytime (OX.4).",
            },
            metadata=metadata or {},
        )
        return self._public(row)

    def get(self, goal_id: str) -> dict[str, Any] | None:
        row = self._repo.get(goal_id)
        return self._public(row) if row else None

    def list(
        self,
        *,
        status: str | None = "active",
        program_id: str | None = None,
        portfolio_key: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        rows = self._repo.list(
            status=status,
            program_id=program_id,
            portfolio_key=portfolio_key,
            limit=limit,
        )
        return {
            "goals": [self._public(r) for r in rows],
            "count": len(rows),
            "version": self.VERSION,
        }

    def search(self, query: str, *, limit: int = 20) -> dict[str, Any]:
        rows = self._repo.search(query, limit=limit)
        return {
            "query": query,
            "goals": [self._public(r) for r in rows],
            "count": len(rows),
            "version": self.VERSION,
        }

    def update(self, goal_id: str, **fields: Any) -> dict[str, Any] | None:
        if "status" in fields and fields["status"] is not None:
            st = str(fields["status"]).strip().lower()
            if st not in GOAL_STATUSES:
                raise ValueError(f"invalid goal status: {st}")
            fields["status"] = st
        if "objective" in fields and fields["objective"] is not None:
            fields["objective"] = _as_objective(fields["objective"])
        if "success_criteria" in fields and fields["success_criteria"] is not None:
            fields["success_criteria"] = _as_criteria(fields["success_criteria"])
        row = self._repo.update(goal_id, **fields)
        return self._public(row) if row else None

    def link(
        self,
        goal_id: str,
        *,
        program_id: str | None = None,
        portfolio_key: str | None = None,
        portfolio_id: str | None = None,
    ) -> dict[str, Any] | None:
        row = self._repo.link(
            goal_id,
            program_id=program_id,
            portfolio_key=portfolio_key,
            portfolio_id=portfolio_id,
        )
        return self._public(row) if row else None

    def ensure_for_learner(
        self,
        *,
        objective_text: str | None,
        capital: float = 10000.0,
        universe: str = "NIFTY50",
        program_id: str = "market_intelligence",
        portfolio_key: str = "india_equity_learner",
        portfolio_id: str | None = None,
    ) -> dict[str, Any]:
        """Create or reuse an active India-learner goal (OX.1/OX.2 activate path)."""
        title = (objective_text or "").strip()
        if not title or title.lower().startswith("start "):
            title = f"Become a profitable investor (₹{capital:,.0f} · {universe})"
        existing = self._repo.list(
            status="active", portfolio_key=portfolio_key, limit=5
        )
        for row in existing:
            return self._public(row)
        return self.create(
            title,
            objective={
                "text": title,
                "intent": "investment_learning",
                "capital": capital,
                "universe": universe,
            },
            success_criteria={
                "text": "Demonstrate positive expectancy in simulation over time",
                "kind": "sim_expectancy",
            },
            program_id=program_id,
            portfolio_key=portfolio_key,
            portfolio_id=portfolio_id,
            metadata={"source": "india_equity_learner", "preset": "india_equity_learner"},
        )

    def resolve(self, query: str) -> dict[str, Any] | None:
        """Best single goal match for Chat (“how is my beat-NIFTY goal?”)."""
        q = (query or "").strip()
        if not q:
            return None
        normalized = re.sub(r"[-_/]+", " ", q)
        hits = self.search(normalized, limit=5).get("goals") or []
        if not hits:
            hits = self.search(q, limit=5).get("goals") or []
        if not hits:
            low = normalized.lower()
            if any(
                k in low
                for k in (
                    "india learner",
                    "learner status",
                    "investment learner",
                    "how is my learner",
                )
            ):
                rows = self._repo.list(
                    status="active", portfolio_key="india_equity_learner", limit=1
                )
                if rows:
                    return self._public(rows[0])
                active = self._repo.list(status="active", limit=1)
                if active:
                    return self._public(active[0])
            tokens = [t for t in _WORD.findall(normalized.lower()) if len(t) > 2]
            skip = {
                "how", "is", "my", "the", "goal", "goals", "doing", "status",
                "show", "what", "about", "with", "for", "over", "months",
                "learner", "india", "progress",
            }
            for tok in tokens:
                if tok in skip:
                    continue
                hits = self.search(tok, limit=5).get("goals") or []
                if hits:
                    break
        return hits[0] if hits else None

    def set_progress(self, goal_id: str, progress: dict[str, Any]) -> dict[str, Any] | None:
        row = self._repo.get(goal_id)
        if row is None:
            return None
        merged = dict(row.get("progress") or {})
        merged.update(progress or {})
        return self.update(goal_id, progress=merged)

    def progress(
        self,
        goal_id: str | None = None,
        *,
        query: str | None = None,
        persist: bool = True,
    ) -> dict[str, Any]:
        """OX.4 — build (and optionally persist) a progress narrative for a Goal."""
        goal = None
        if goal_id:
            goal = self.get(goal_id)
        if goal is None and query:
            goal = self.resolve(query)
        if goal is None:
            return {
                "ok": False,
                "error": "goal_not_found",
                "narrative": "No matching goal — create one with “my goal is …” first.",
                "bullets": [],
                "version": self.VERSION,
            }

        book = None
        pkey = goal.get("portfolio_key")
        if pkey:
            try:
                from atlas.investment import portfolios as vp

                book = vp.get(str(pkey))
            except Exception as exc:  # noqa: BLE001
                self._logger.debug("portfolio registry lookup skipped: %s", exc)

        snapshot = self._snapshot_for(book, goal)
        watchlist = self._watchlist_for(goal, book)
        mentor = self._mentor_for(goal)

        report = build_progress_report(
            goal,
            book=book,
            snapshot=snapshot,
            watchlist=watchlist,
            mentor_advice=mentor,
        )
        report["ok"] = True
        report["answer"] = format_progress_answer(report)
        if persist:
            try:
                updated = self.set_progress(str(goal["id"]), report["progress"])
                if updated:
                    report["goal"] = updated
            except Exception as exc:  # noqa: BLE001
                self._logger.debug("persist progress skipped: %s", exc)
        return report

    def learner_status(self, *, query: str = "india learner") -> dict[str, Any]:
        """Convenience: progress for the India learner goal (or best active match)."""
        report = self.progress(query=query or "india learner", persist=True)
        try:
            from atlas.investment.happy_path import happy_path_status
            from atlas.investment.screener_signals import latest_snapshot

            goal = report.get("goal") if isinstance(report.get("goal"), dict) else None
            book = None
            if goal and goal.get("portfolio_key"):
                try:
                    from atlas.investment import portfolios as vp

                    book = vp.get(str(goal["portfolio_key"]))
                except Exception:  # noqa: BLE001
                    book = None
            wl = self._watchlist_for(goal or {}, book) if goal else None
            snap = self._snapshot_for(book, goal or {}) if goal else None
            screener = latest_snapshot(
                str((goal or {}).get("program_id") or "market_intelligence")
            )
            scount = int((screener or {}).get("count") or 0)
            report["happy_path"] = happy_path_status(
                goal=goal,
                watchlist=wl,
                book=book,
                snapshot=snap,
                screener_count=scount,
            )
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("happy_path attach skipped: %s", exc)
        return report

    def _snapshot_for(
        self, book: dict[str, Any] | None, goal: dict[str, Any]
    ) -> dict[str, Any] | None:
        if self._portfolio is None:
            return None
        mid = None
        name = goal.get("portfolio_key") or "default"
        if isinstance(book, dict):
            mid = book.get("mission_id")
            name = book.get("portfolio_key") or name
        if not mid:
            return None
        try:
            cash = 10000.0
            if isinstance(book, dict) and isinstance(book.get("persona"), dict):
                cash = float(book["persona"].get("capital") or cash)
            ensured = self._portfolio.ensure_portfolio(
                mission_id=mid, name=name, starting_cash=cash
            )
            return self._portfolio.snapshot(ensured["id"])
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("portfolio snapshot skipped: %s", exc)
            return None

    def _watchlist_for(
        self, goal: dict[str, Any], book: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        try:
            from atlas.investment import watchlists as wl

            program_id = (
                (book or {}).get("program_id")
                or goal.get("program_id")
                or wl.DEFAULT_PROGRAM
            )
            return wl.latest(str(program_id))
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("watchlist lookup skipped: %s", exc)
            return None

    def _mentor_for(self, goal: dict[str, Any]) -> str | None:
        pkey = goal.get("portfolio_key")
        query = "markets"
        if pkey:
            query = f"markets portfolio:{pkey}"
        try:
            if self._experience_os is not None:
                adv = self._experience_os.advice_for(query, limit=3)
            elif self._learning is not None:
                adv = self._learning.advice_for(query, limit=3)
            else:
                return None
            if not isinstance(adv, dict):
                return None
            if pkey:
                from atlas.investment.portfolios import filter_journals_for_portfolio

                journals = filter_journals_for_portfolio(
                    adv.get("journals") or [], str(pkey)
                )
                if not journals:
                    return None
            text = str(adv.get("advice") or "").strip()
            return text or None
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("mentor advice skipped: %s", exc)
            return None

    @staticmethod
    def _public(row: dict[str, Any] | None) -> dict[str, Any]:
        if not row:
            return {}
        out = dict(row)
        out["id"] = str(out.get("id") or "")
        for key in ("objective", "success_criteria", "progress", "metadata"):
            val = out.get(key)
            if val is None and key == "success_criteria":
                continue
            if not isinstance(val, dict):
                out[key] = {} if key != "success_criteria" else None
        return out


def _as_objective(raw: dict[str, Any] | str | None, *, fallback_text: str = "") -> dict[str, Any]:
    if isinstance(raw, dict):
        out = dict(raw)
        if "text" not in out:
            out["text"] = str(out.get("intent") or fallback_text or "").strip()
        return out
    text = str(raw).strip() if raw else fallback_text
    return {"text": text}


def _as_criteria(raw: dict[str, Any] | str | None) -> dict[str, Any] | None:
    if raw is None:
        return None
    if isinstance(raw, dict):
        return dict(raw)
    text = str(raw).strip()
    return {"text": text} if text else None
