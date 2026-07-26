"""Investor email reports — morning plan + trade decision digests.

Uses shared SMTP EmailSender with per-send recipients (Gmail app password via env).
Market Program only — not a new OS; not ops Notifier fan-out.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

from atlas.investment.daily_plan import plan_from_watchlist
from atlas.investment.government_policy import format_policy_brief, load_snapshot


def parse_recipients(raw: str | list[str] | None) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    return [p.strip() for p in str(raw).split(",") if p.strip()]


def resolve_investor_recipients(
    *,
    config_to: list[str] | None = None,
    env: dict[str, str] | None = None,
) -> list[str]:
    """Prefer dedicated investor env, then email to_addrs env, then config list."""
    env = env if env is not None else os.environ
    for key in (
        "ATLAS_INVESTOR_REPORT_TO",
        "ATLAS_EMAIL_INVESTOR_TO_ADDRS",
        "ATLAS_EMAIL_TO_ADDRS",
    ):
        if env.get(key):
            return parse_recipients(env.get(key))
    return list(config_to or [])


def format_morning_report(
    *,
    plan: dict[str, Any] | None,
    portfolio: dict[str, Any] | None = None,
    policy_snap: dict[str, Any] | None = None,
    program_id: str = "market_intelligence",
    research_digest: dict[str, Any] | None = None,
) -> tuple[str, str]:
    plan = plan or {}
    as_of = plan.get("as_of") or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    subject = f"[Atlas] Morning investment plan — {as_of} ({program_id})"
    lines = [
        "Atlas morning report (simulation — not broker orders)",
        f"Date: {as_of}",
        f"Program: {program_id}",
        f"Phase: {plan.get('phase')} · confidence: {plan.get('confidence')}",
        f"Capital: {plan.get('capital')} · deploy fraction: {plan.get('deploy_fraction')}",
        "",
        "Summary:",
        str(plan.get("summary") or "(no plan yet)"),
        "",
        "Selected candidates — why & suggested notional:",
    ]
    for c in plan.get("candidates") or []:
        lines.append(
            f"  {c.get('rank', '?')}. {c.get('symbol')} ({c.get('sector') or '—'}) "
            f"— ₹{c.get('suggested_notional', 0)} "
            f"(weight {c.get('suggested_weight', 0)})"
        )
        why = (c.get("why") or "").strip()
        if why:
            lines.append(f"     Why: {why}")
        for ex in (c.get("explanations") or [])[:4]:
            if isinstance(ex, dict):
                lines.append(f"     {ex.get('sign', '·')} {ex.get('text', '')}")
            else:
                lines.append(f"     · {ex}")
        # IRA morning: thesis one-liner when digest provided
        if research_digest:
            for s in research_digest.get("studied") or []:
                if s.get("symbol") == c.get("symbol") and s.get("thesis"):
                    lines.append(
                        f"     Thesis ({s.get('stance') or '?'}): {s.get('thesis')} "
                        f"[cov {s.get('coverage')}% / conf {s.get('confidence')}]"
                    )
                    break
    avoids = plan.get("avoids") or []
    if avoids:
        lines.append("")
        lines.append("Avoid / weaker relative set:")
        for a in avoids[:8]:
            if isinstance(a, dict):
                lines.append(f"  - {a.get('symbol')}: {a.get('why') or a.get('reason') or ''}")
            else:
                lines.append(f"  - {a}")
    for note in plan.get("notes") or []:
        lines.append(f"Note: {note}")

    if portfolio:
        lines.append("")
        lines.append("Current portfolio snapshot:")
        lines.append(f"  Cash: {portfolio.get('cash')}")
        lines.append(f"  Equity value: {portfolio.get('equity_value') or portfolio.get('positions_value')}")
        pos = portfolio.get("positions") or portfolio.get("holdings") or []
        if isinstance(pos, dict):
            pos = [{"symbol": k, **(v if isinstance(v, dict) else {})} for k, v in pos.items()]
        for p in list(pos)[:20]:
            if not isinstance(p, dict):
                continue
            lines.append(
                f"  · {p.get('symbol')}: qty={p.get('quantity') or p.get('qty')} "
                f"avg={p.get('avg_price') or p.get('avg_cost')}"
            )

    if policy_snap:
        lines.append("")
        lines.append(format_policy_brief(policy_snap, limit=6))

    _append_research_section(lines, research_digest, heading="Research studied (IRA)")

    lines.append("")
    lines.append("— Atlas Resource OS / Market Program · P10 simulation only")
    return subject, "\n".join(lines)


def format_evening_report(
    *,
    plan: dict[str, Any] | None,
    portfolio: dict[str, Any] | None = None,
    policy_snap: dict[str, Any] | None = None,
    program_id: str = "market_intelligence",
    trades: list[dict[str, Any]] | None = None,
    research_digest: dict[str, Any] | None = None,
) -> tuple[str, str]:
    """Post-NSE close digest: what we planned, what filled, portfolio end state."""
    plan = plan or {}
    as_of = plan.get("as_of") or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    subject = f"[Atlas] Evening EOD digest — {as_of} ({program_id})"
    lines = [
        "Atlas evening report (simulation — not broker orders)",
        f"Date: {as_of}",
        f"Program: {program_id}",
        "Window: after NSE cash equity close (~15:30 IST)",
        f"Morning phase was: {plan.get('phase')} · confidence: {plan.get('confidence')}",
        "",
        "Morning plan recap:",
        str(plan.get("summary") or "(no plan recorded)"),
        "",
        "Candidates (planned) — why & suggested notional:",
    ]
    for c in plan.get("candidates") or []:
        lines.append(
            f"  {c.get('rank', '?')}. {c.get('symbol')} ({c.get('sector') or '—'}) "
            f"— ₹{c.get('suggested_notional', 0)} "
            f"(weight {c.get('suggested_weight', 0)})"
        )
        why = (c.get("why") or "").strip()
        if why:
            lines.append(f"     Why: {why}")
        for ex in (c.get("explanations") or [])[:4]:
            if isinstance(ex, dict):
                lines.append(f"     {ex.get('sign', '·')} {ex.get('text', '')}")
            else:
                lines.append(f"     · {ex}")

    trades = list(trades or [])
    if portfolio and not trades:
        trades = list(portfolio.get("recent_trades") or [])
    lines.append("")
    lines.append(f"Simulated fills today / recent ({len(trades)}):")
    if not trades:
        lines.append("  (no fills recorded in this snapshot)")
    for t in trades[:25]:
        if not isinstance(t, dict):
            continue
        side = (t.get("side") or t.get("action") or "?").upper()
        lines.append(
            f"  · {side} {t.get('symbol')} × {t.get('quantity') or t.get('qty')} "
            f"@ {t.get('price') or t.get('fill_price')}"
            + (
                f" — {t.get('reason') or t.get('note') or ''}"
                if (t.get("reason") or t.get("note"))
                else ""
            )
        )
        for key in ("rationale", "why"):
            if t.get(key):
                lines.append(f"     {t.get(key)}")

    if portfolio:
        lines.append("")
        lines.append("End-of-day portfolio snapshot:")
        lines.append(f"  Cash: {portfolio.get('cash')}")
        lines.append(
            f"  Equity value: {portfolio.get('equity_value') or portfolio.get('positions_value')}"
        )
        if portfolio.get("trade_count") is not None:
            lines.append(f"  Trade count (ledger): {portfolio.get('trade_count')}")
        if portfolio.get("fees_paid") is not None:
            lines.append(f"  Fees paid: {portfolio.get('fees_paid')}")
        pos = portfolio.get("positions") or portfolio.get("holdings") or []
        if isinstance(pos, dict):
            pos = [{"symbol": k, **(v if isinstance(v, dict) else {})} for k, v in pos.items()]
        for p in list(pos)[:20]:
            if not isinstance(p, dict):
                continue
            lines.append(
                f"  · {p.get('symbol')}: qty={p.get('quantity') or p.get('qty')} "
                f"avg={p.get('avg_price') or p.get('avg_cost')}"
            )

    if policy_snap:
        lines.append("")
        lines.append(format_policy_brief(policy_snap, limit=6))

    _append_research_section(
        lines,
        research_digest,
        heading="Research studied / decided / learned (IRA)",
        evening=True,
    )

    lines.append("")
    lines.append("— Atlas Resource OS / Market Program · P10 simulation only")
    return subject, "\n".join(lines)


def _append_research_section(
    lines: list[str],
    digest: dict[str, Any] | None,
    *,
    heading: str,
    evening: bool = False,
) -> None:
    if not digest:
        return
    studied = list(digest.get("studied") or [])
    lessons = list(digest.get("lessons") or [])
    gaps = list(digest.get("open_gaps") or [])
    if not (studied or lessons or gaps):
        return
    lines.append("")
    lines.append(heading + ":")
    if studied:
        lines.append("  Studied:")
        for s in studied[:10]:
            mvr = "MVR✓" if s.get("mvr_satisfied") else "MVR…"
            lines.append(
                f"  · {s.get('symbol')} [{mvr}] cov={s.get('coverage')}% "
                f"conf={s.get('confidence')} phase={s.get('phase')}"
            )
            if s.get("thesis"):
                lines.append(f"     Thesis ({s.get('stance') or '?'}): {s.get('thesis')}")
    if evening and lessons:
        lines.append("  Lessons from trading experience:")
        for lesson in lessons[-8:]:
            lines.append(f"  · {lesson}")
    if gaps:
        lines.append("  Open questions / gaps (fact ≠ estimate ≠ gap):")
        for g in gaps[:8]:
            lines.append(f"  · {g}")


def format_weekly_research_report(
    *,
    digest: dict[str, Any] | None,
    program_id: str = "market_intelligence",
) -> tuple[str, str]:
    """IRA.17 — weekly research learning digest."""
    digest = digest or {}
    as_of = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    subject = f"[Atlas] Weekly research learning — {as_of} ({program_id})"
    lines = [
        "Atlas weekly research learning digest (simulation — not broker orders)",
        f"Date: {as_of}",
        f"Program: {program_id}",
        f"Dossiers tracked: {digest.get('count') or 0}",
        "",
        "What we studied:",
    ]
    studied = list(digest.get("studied") or [])
    if not studied:
        lines.append("  (no research dossiers yet — run on-demand Research or paper ticks)")
    for s in studied[:12]:
        lines.append(
            f"  · {s.get('symbol')} [{('MVR✓' if s.get('mvr_satisfied') else 'MVR…')}] "
            f"cov={s.get('coverage')}% conf={s.get('confidence')} stance={s.get('stance')}"
        )
        if s.get("thesis"):
            lines.append(f"     {s.get('thesis')}")
    lines.append("")
    lines.append("Belief changes / ThesisOutcomes:")
    changes = list(digest.get("belief_changes") or digest.get("lessons") or [])
    if not changes:
        lines.append("  (no held/weakened/falsified outcomes yet)")
    for c in changes[:15]:
        lines.append(f"  · {c}")
    gaps = list(digest.get("open_gaps") or [])
    if gaps:
        lines.append("")
        lines.append("Open gaps (fact ≠ estimate ≠ gap):")
        for g in gaps[:10]:
            lines.append(f"  · {g}")
    lines.append("")
    lines.append("— Atlas Resource OS / Market Program · P10 simulation only")
    return subject, "\n".join(lines)


def format_trade_report(
    *,
    side: str,
    symbol: str,
    quantity: float,
    price: float,
    fee: float = 0.0,
    reason: str = "",
    decision: dict[str, Any] | None = None,
    mission_id: str | None = None,
    fees: dict[str, Any] | None = None,
    realized_pnl: float | None = None,
    policy_note: str = "",
    thesis: dict[str, Any] | None = None,
) -> tuple[str, str]:
    side_u = (side or "").upper()
    subject = f"[Atlas] {side_u} {symbol} × {quantity:g} @ {price:.2f}"
    lines = [
        "Atlas trade decision report (simulation fill)",
        f"Time (UTC): {datetime.now(timezone.utc).isoformat()}",
        f"Side: {side_u}",
        f"Symbol: {symbol}",
        f"Quantity: {quantity:g}",
        f"Price: {price:.4f}",
        f"Fee: {fee:.4f}",
    ]
    if fees:
        lines.append(f"Fee breakdown: {fees}")
    if realized_pnl is not None:
        lines.append(f"Realized PnL: {realized_pnl:.4f}")
    if mission_id:
        lines.append(f"Mission: {mission_id}")
    if reason:
        lines.append("")
        lines.append(f"Why (tick summary): {reason}")
    if decision:
        lines.append("")
        lines.append("Decision detail:")
        for key in ("id", "action", "rationale", "confidence", "rule", "status"):
            if decision.get(key) is not None:
                lines.append(f"  {key}: {decision.get(key)}")
        opts = decision.get("options") or decision.get("chosen") or {}
        if isinstance(opts, dict) and opts:
            lines.append(f"  options: {opts}")
        expl = decision.get("explanations") or decision.get("why") or []
        if isinstance(expl, str) and expl:
            lines.append(f"  why: {expl}")
        elif isinstance(expl, list):
            for e in expl[:8]:
                lines.append(f"  · {e}")
    if thesis and isinstance(thesis, dict):
        lines.append("")
        lines.append(f"Linked thesis: {thesis.get('id') or '(none)'}")
        if thesis.get("summary"):
            lines.append(f"  {thesis.get('summary')}")
        if thesis.get("falsifiers"):
            lines.append(f"  Falsifiers: {', '.join(str(x) for x in thesis.get('falsifiers')[:4])}")
    if policy_note:
        lines.append("")
        lines.append(f"Policy / government context: {policy_note}")
    lines.append("")
    lines.append("Not a live broker order. Simulation Program only (P10).")
    return subject, "\n".join(lines)


class InvestorReportMailer:
    """Thin wrapper: build report bodies and send via EmailSender.send_to."""

    name = "investor_reports"
    VERSION = "ir.2"

    def __init__(
        self,
        email: Any,
        *,
        data_dir: str | None = None,
        recipients: list[str] | None = None,
        enabled: bool = True,
        research: Any | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._email = email
        self._data_dir = data_dir
        self._recipients = list(recipients or [])
        self._enabled = bool(enabled)
        self._research = research
        self._logger = logger or logging.getLogger("atlas.investment.reports")
        self._sent_morning_dates: set[str] = set()
        self._sent_evening_dates: set[str] = set()
        self._sent_weekly_keys: set[str] = set()

    def bind_research(self, research: Any) -> None:
        self._research = research

    def _research_digest(self, program_id: str) -> dict[str, Any] | None:
        if self._research is None or not hasattr(self._research, "daily_digest"):
            return None
        try:
            return self._research.daily_digest(program_id=program_id)
        except Exception:  # noqa: BLE001
            self._logger.debug("research digest failed", exc_info=True)
            return None

    def recipients(self) -> list[str]:
        got = resolve_investor_recipients(config_to=self._recipients)
        return got

    def available(self) -> bool:
        if not self._enabled:
            return False
        if self._email is None:
            return False
        to = self.recipients()
        if not to:
            return False
        if hasattr(self._email, "smtp_ready"):
            return bool(self._email.smtp_ready())
        if hasattr(self._email, "can_send"):
            return bool(self._email.can_send())
        return bool(getattr(self._email, "available", lambda: False)())

    def status(self) -> dict[str, Any]:
        """Config readiness for the Market page (no secrets)."""
        smtp = {}
        if self._email is not None and hasattr(self._email, "status"):
            try:
                smtp = self._email.status()
            except Exception:  # noqa: BLE001
                smtp = {}
        recipients = self.recipients()
        ready = self.available()
        missing: list[str] = []
        if not smtp.get("host"):
            missing.append("ATLAS_EMAIL_HOST (e.g. smtp.gmail.com)")
        if not smtp.get("from_addr") and not smtp.get("username"):
            missing.append("ATLAS_EMAIL_USERNAME / ATLAS_EMAIL_FROM_ADDR")
        if not smtp.get("password_set"):
            missing.append("ATLAS_SMTP_PASSWORD (Gmail App Password)")
        if not recipients:
            missing.append("ATLAS_INVESTOR_REPORT_TO (comma-separated receivers)")
        return {
            "version": self.VERSION,
            "enabled": self._enabled,
            "ready": ready,
            "recipients": recipients,
            "smtp": smtp,
            "missing": missing,
            "hint": (
                "Set Gmail App Password + receivers in .env, restart Atlas, "
                "then Preview → Send on the Market page."
                if missing
                else "SMTP looks configured — Preview the report, then Send test email."
            ),
        }

    def preview_morning(
        self,
        *,
        program_id: str = "market_intelligence",
        portfolio: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build the morning email without sending — for Market page review."""
        from atlas.investment import watchlists as wl

        snap = wl.latest(program_id)
        plan = None
        if isinstance(snap, dict):
            plan = (snap.get("extra") or {}).get("daily_plan") or snap.get("daily_plan")
            if not plan:
                plan = plan_from_watchlist(snap)
        policy = load_snapshot(self._data_dir) if self._data_dir else None
        subject, body = format_morning_report(
            plan=plan,
            portfolio=portfolio,
            policy_snap=policy,
            program_id=program_id,
            research_digest=self._research_digest(program_id),
        )
        return {
            "subject": subject,
            "body": body,
            "recipients": self.recipients(),
            "ready": self.available(),
            "has_plan": bool(plan and (plan.get("candidates") or plan.get("summary"))),
            "as_of": (plan or {}).get("as_of"),
        }

    def send_morning(
        self,
        *,
        program_id: str = "market_intelligence",
        portfolio: dict[str, Any] | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        preview = self.preview_morning(program_id=program_id, portfolio=portfolio)
        if not self.available():
            return {
                "sent": False,
                "reason": "email_unavailable",
                "status": self.status(),
                **{k: preview[k] for k in ("subject", "body", "recipients", "as_of")},
            }
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if not force and today in self._sent_morning_dates:
            return {
                "sent": False,
                "reason": "already_sent_today",
                "as_of": today,
                **{k: preview[k] for k in ("subject", "body", "recipients")},
            }
        ok = self._deliver(preview["subject"], preview["body"])
        if ok:
            self._sent_morning_dates.add(today)
        return {
            "sent": ok,
            "as_of": today,
            "recipients": preview["recipients"],
            "subject": preview["subject"],
            "body": preview["body"],
            "reason": None if ok else "smtp_send_failed",
        }

    def preview_evening(
        self,
        *,
        program_id: str = "market_intelligence",
        portfolio: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from atlas.investment import watchlists as wl

        snap = wl.latest(program_id)
        plan = None
        if isinstance(snap, dict):
            plan = (snap.get("extra") or {}).get("daily_plan") or snap.get("daily_plan")
            if not plan:
                plan = plan_from_watchlist(snap)
        policy = load_snapshot(self._data_dir) if self._data_dir else None
        subject, body = format_evening_report(
            plan=plan,
            portfolio=portfolio,
            policy_snap=policy,
            program_id=program_id,
            trades=(portfolio or {}).get("recent_trades") if isinstance(portfolio, dict) else None,
            research_digest=self._research_digest(program_id),
        )
        return {
            "subject": subject,
            "body": body,
            "recipients": self.recipients(),
            "ready": self.available(),
            "has_plan": bool(plan and (plan.get("candidates") or plan.get("summary"))),
            "as_of": (plan or {}).get("as_of"),
        }

    def send_evening(
        self,
        *,
        program_id: str = "market_intelligence",
        portfolio: dict[str, Any] | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        preview = self.preview_evening(program_id=program_id, portfolio=portfolio)
        if not self.available():
            return {
                "sent": False,
                "reason": "email_unavailable",
                "status": self.status(),
                **{k: preview[k] for k in ("subject", "body", "recipients", "as_of")},
            }
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if not force and today in self._sent_evening_dates:
            return {
                "sent": False,
                "reason": "already_sent_today",
                "as_of": today,
                **{k: preview[k] for k in ("subject", "body", "recipients")},
            }
        ok = self._deliver(preview["subject"], preview["body"])
        if ok:
            self._sent_evening_dates.add(today)
        return {
            "sent": ok,
            "as_of": today,
            "recipients": preview["recipients"],
            "subject": preview["subject"],
            "body": preview["body"],
            "reason": None if ok else "smtp_send_failed",
        }

    def send_trade(self, **kwargs: Any) -> dict[str, Any]:
        if not self.available():
            return {"sent": False, "reason": "email_unavailable", "status": self.status()}
        if "thesis" not in kwargs and self._research is not None and kwargs.get("symbol"):
            try:
                aw = self._research.awareness(str(kwargs["symbol"]))
                if isinstance(aw.get("thesis"), dict):
                    kwargs = {**kwargs, "thesis": aw.get("thesis")}
            except Exception:  # noqa: BLE001
                pass
        subject, body = format_trade_report(**kwargs)
        ok = self._deliver(subject, body)
        return {
            "sent": ok,
            "recipients": self.recipients(),
            "subject": subject,
            "body": body,
            "reason": None if ok else "smtp_send_failed",
        }

    def preview_weekly_research(
        self,
        *,
        program_id: str = "market_intelligence",
    ) -> dict[str, Any]:
        digest = None
        if self._research is not None and hasattr(self._research, "weekly_learning_digest"):
            try:
                digest = self._research.weekly_learning_digest(program_id=program_id)
            except Exception:  # noqa: BLE001
                self._logger.debug("weekly digest failed", exc_info=True)
                digest = None
        subject, body = format_weekly_research_report(digest=digest, program_id=program_id)
        return {
            "subject": subject,
            "body": body,
            "recipients": self.recipients(),
            "ready": self.available(),
            "digest": digest,
        }

    def send_weekly_research(
        self,
        *,
        program_id: str = "market_intelligence",
        force: bool = False,
    ) -> dict[str, Any]:
        preview = self.preview_weekly_research(program_id=program_id)
        if not self.available():
            return {
                "sent": False,
                "reason": "email_unavailable",
                "status": self.status(),
                **{k: preview[k] for k in ("subject", "body", "recipients")},
            }
        # ISO week key
        today = datetime.now(timezone.utc)
        week_key = f"{today.isocalendar()[0]}-W{today.isocalendar()[1]:02d}"
        if not force and week_key in self._sent_weekly_keys:
            return {
                "sent": False,
                "reason": "already_sent_this_week",
                "week": week_key,
                **{k: preview[k] for k in ("subject", "body", "recipients")},
            }
        ok = self._deliver(preview["subject"], preview["body"])
        if ok:
            self._sent_weekly_keys.add(week_key)
        return {
            "sent": ok,
            "week": week_key,
            "recipients": preview["recipients"],
            "subject": preview["subject"],
            "body": preview["body"],
            "reason": None if ok else "smtp_send_failed",
        }

    def _deliver(self, subject: str, body: str) -> bool:
        to = self.recipients()
        try:
            if hasattr(self._email, "send_to"):
                return bool(self._email.send_to(to, subject, body))
            return bool(self._email.send(subject, body))
        except Exception:  # noqa: BLE001
            self._logger.exception("investor report send failed")
            return False
