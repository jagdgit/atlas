"""MDPH Zerodha login email + IMAP reply poll (request_token only).

Flow:
  LOGIN_REQUIRED / EXPIRED
      → once/day escalate email with public login link + reply instructions
      → while awaiting, poll IMAP every ~5 minutes
      → parse ATLAS_ZERODHA_REQUEST_TOKEN (or request_token=…)
      → ZerodhaMarketFeed.complete_login(request_token)
      → confirm mail (no secrets)

Never logs request_token / access_token. Prefer browser /zerodha/login when reachable;
reply path is for power-cut / off-LAN days.
"""

from __future__ import annotations

import logging
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

_log = logging.getLogger("atlas.investment.zerodha_token_email")
_IST = ZoneInfo("Asia/Kolkata")

VERSION = "mdph.zerodha_token_email.v1"
STORE_REL = Path("investment") / "market_data_provider"
PENDING_NAME = "token_email_pending.json"

REQUEST_TOKEN_LINE = re.compile(
    r"(?im)^\s*ATLAS_ZERODHA_REQUEST_TOKEN\s*[:=]\s*([A-Za-z0-9_\-]{10,64})\s*$"
)
REQUEST_TOKEN_INLINE = re.compile(
    r"(?i)ATLAS_ZERODHA_REQUEST_TOKEN\s*[:=]\s*([A-Za-z0-9_\-]{10,64})"
)
REQUEST_TOKEN_QUERY = re.compile(
    r"(?i)(?:\?|&)request_token=([A-Za-z0-9_\-]{10,64})"
)
# Kite requires ≥10 chars. Never accept instructional English from our own mail.
_REQUEST_TOKEN_VALUE = re.compile(r"^[A-Za-z0-9_-]{10,64}$")
_REQUEST_TOKEN_BLOCKLIST = frozenset(
    {
        "optional",
        "request",
        "token",
        "prefix",
        "success",
        "login",
        "callback",
        "zerodha",
        "required",
    }
)

POLL_INTERVAL_S = 60  # Kite request_token dies in minutes; 5m was too slow
SUBJECT_PREFIX = "[Atlas MDPH] Zerodha"


def _ist_day() -> str:
    return datetime.now(_IST).date().isoformat()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def atlas_public_base_url() -> str:
    """Operator-reachable Atlas origin for email CTAs (not secrets).

    Ignores placeholder values like ``http://<datanode-hostname-or-IP>:8000``
    so reply-first mail stays correct when there is no real public URL.
    """
    for key in ("ATLAS_PUBLIC_BASE_URL", "ATLAS_BASE_URL"):
        raw = (os.environ.get(key) or "").strip().rstrip("/")
        if not raw:
            continue
        low = raw.lower()
        # Common copy-paste placeholders from docs — treat as unset.
        if "<" in raw or ">" in raw or "hostname-or-ip" in low or "your-" in low:
            continue
        return raw
    redirect = (os.environ.get("ZERODHA_REDIRECT_URL") or "").strip()
    if redirect:
        try:
            p = urlparse(redirect)
            if p.scheme and p.netloc and "<" not in p.netloc:
                return f"{p.scheme}://{p.netloc}".rstrip("/")
        except Exception:  # noqa: BLE001
            pass
    return "http://127.0.0.1:8000"


def login_cta_url(*, force: bool = False) -> str:
    base = atlas_public_base_url()
    path = "/zerodha/force-login" if force else "/zerodha/login"
    return f"{base}{path}"


def _plausible_request_token(value: str | None) -> str | None:
    """Accept only Kite-shaped tokens. Reject instructional prose like ``... even though``."""
    tok = str(value or "").strip()
    if not tok or not _REQUEST_TOKEN_VALUE.fullmatch(tok):
        return None
    if set(tok) <= {".", "-", "_"} or tok.lower() in _REQUEST_TOKEN_BLOCKLIST:
        return None
    return tok


def parse_request_token_from_text(text: str | None) -> str | None:
    """Extract a short-lived Kite request_token from a reply body. Never log it.

    Prefer ``?request_token=`` in a callback URL over the ATLAS_… label form, so
    instructional text like ``ATLAS_ZERODHA_REQUEST_TOKEN: prefix…`` cannot beat
    a real pasted login URL in the same reply.
    """
    blob = str(text or "")
    if not blob.strip():
        return None
    # 1) Callback / redirect URL (primary path from phone replies)
    for line in blob.splitlines():
        line = line.strip()
        if "request_token=" not in line.lower():
            continue
        try:
            if "://" in line:
                qs = parse_qs(urlparse(line).query)
            else:
                qs = parse_qs(line.split("?", 1)[-1])
            vals = qs.get("request_token") or qs.get("requestToken") or []
            if not vals:
                continue
            tok = _plausible_request_token(str(vals[0]))
            if tok:
                return tok
        except Exception:  # noqa: BLE001
            continue
    m = REQUEST_TOKEN_QUERY.search(blob)
    if m:
        tok = _plausible_request_token(m.group(1))
        if tok:
            return tok
    # 2) Explicit ATLAS_ZERODHA_REQUEST_TOKEN line (operator paste of bare token)
    for rx in (REQUEST_TOKEN_LINE, REQUEST_TOKEN_INLINE):
        m = rx.search(blob)
        if m:
            tok = _plausible_request_token(m.group(1))
            if tok:
                return tok
    return None


def _pending_path(data_dir: str | Path | None) -> Path | None:
    if not data_dir:
        return None
    return Path(data_dir) / STORE_REL / PENDING_NAME


def load_pending(data_dir: str | Path | None) -> dict[str, Any]:
    path = _pending_path(data_dir)
    if path is None or not path.is_file():
        return {}
    try:
        import json

        doc = json.loads(path.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def save_pending(data_dir: str | Path | None, doc: dict[str, Any]) -> None:
    path = _pending_path(data_dir)
    if path is None:
        return
    try:
        import json

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc, indent=2, default=str) + "\n", encoding="utf-8")
    except OSError:
        _log.debug("token_email pending write failed", exc_info=True)


def is_loopback_base(url: str | None = None) -> bool:
    base = (url or atlas_public_base_url()).lower()
    return "127.0.0.1" in base or "localhost" in base


def resolve_kite_login_url(
    *, data_dir: str | Path | None = None, feed: Any | None = None
) -> str | None:
    """Zerodha-hosted login URL (public) — does not require Atlas to be reachable."""
    try:
        from atlas.investment.zerodha_feed import ZerodhaMarketFeed

        zfeed = feed or ZerodhaMarketFeed.from_env(data_dir=data_dir)
        out = zfeed.login_url()
        if out.get("ok") and out.get("login_url"):
            return str(out["login_url"])
    except Exception:  # noqa: BLE001
        _log.debug("kite login_url unavailable", exc_info=True)
    return None


def build_escalate_body(
    *,
    status: str,
    trading_date: str,
    login_url: str,
    force_login_url: str,
    public_base: str,
    kite_login_url: str | None = None,
) -> str:
    """Email body. When Atlas has no public URL, reply-with-token is the primary path."""
    loopback = is_loopback_base(public_base)
    kite = (kite_login_url or "").strip()
    lines = [
        f"Provider status: {status}",
        f"Trading date (IST): {trading_date}",
        "Live-required labs (intraday / F&O) are paused until Zerodha login.",
        "",
    ]
    if loopback:
        lines += [
            "Atlas is on a private/loopback address (no public URL / static IP).",
            "You do NOT need to reach Atlas in a browser. Use the reply path below.",
            "",
            "PRIMARY — reply to THIS email (works from phone, any network):",
            "  1) Open the Zerodha Kite login link (Zerodha's site, not Atlas):",
        ]
        if kite:
            lines.append(f"       {kite}")
        else:
            lines.append(
                "       (Kite login URL unavailable — open kite.zerodha.com "
                "Connect login for your API key, or use Atlas host on LAN later.)"
            )
        lines += [
            "  2) Complete user id / password / TOTP.",
            "  3) Browser will try to open http://127.0.0.1:8000/... and show",
            "     'site can't be reached' / Connection refused.",
            "     THAT IS EXPECTED — login already succeeded at Zerodha.",
            "  4) Do NOT close the tab. Copy the FULL address-bar URL",
            "     (long-press the URL → Copy). It still contains the",
            "     request_token query param even though the page failed.",
            "  5) Reply to this email and paste the copied URL alone.",
            "     No label needed — paste the full",
            "     http://127.0.0.1:8000/... callback URL on one line.",
            "",
            "Atlas reads this mailbox about every minute and exchanges the",
            "request_token server-side. Do NOT paste the daily access_token.",
            "Send the reply within a couple of minutes — Kite expires it quickly.",
            "",
            "OPTIONAL — only if you SSH-tunnel to the Atlas host first",
            "  (ssh -L 8000:127.0.0.1:8000 <host>), then:",
            f"  {login_url}",
            f"  {force_login_url}",
            f"  (local base: {public_base})",
        ]
    else:
        lines += [
            "Option A — open Atlas in a browser:",
            f"  Login: {login_url}",
            f"  Force fresh session: {force_login_url}",
            "",
        ]
        if kite:
            lines += [
                "Or open Zerodha directly:",
                f"  {kite}",
                "",
            ]
        lines += [
            "Option B — reply to THIS email with one line:",
            "  ATLAS_ZERODHA_REQUEST_TOKEN: <paste_request_token_or_full_redirect_url>",
            "",
            "After 2FA, copy the redirect URL (it includes request_token).",
            "Do NOT paste the daily access_token. Atlas polls mail ~every minute.",
            "Reply within a couple of minutes — Kite expires the token quickly.",
            f"Public base: {public_base}",
        ]
    return "\n".join(lines) + "\n"


def _email_sender() -> Any | None:
    try:
        import os as _os

        from atlas.config import get_config
        from atlas.investment.reports import resolve_investor_recipients
        from atlas.notify.email import EmailSender

        cfg = get_config()
        email_cfg = cfg.email
        password = _os.environ.get(str(getattr(email_cfg, "password_env", "") or ""), "")
        # Prefer ATLAS_INVESTOR_REPORT_TO (same as morning/trade mail) — config
        # investor_to_addrs is often empty when only the env alias is set.
        to_addrs = resolve_investor_recipients(
            config_to=list(
                getattr(email_cfg, "investor_to_addrs", None)
                or getattr(email_cfg, "to_addrs", None)
                or []
            )
        )
        sender = EmailSender(
            host=str(getattr(email_cfg, "host", "") or ""),
            port=int(getattr(email_cfg, "port", 587) or 587),
            username=str(getattr(email_cfg, "username", "") or ""),
            password=password,
            from_addr=str(getattr(email_cfg, "from_addr", "") or ""),
            to_addrs=to_addrs,
            use_tls=bool(getattr(email_cfg, "use_tls", True)),
            timeout=float(getattr(email_cfg, "timeout", 20.0) or 20.0),
        )
        if not sender.available():
            return None
        return sender
    except Exception:  # noqa: BLE001
        _log.debug("email sender build failed", exc_info=True)
        return None


def _mail_client() -> Any | None:
    """IMAP reader: plugins.mail if set, else Gmail IMAP using SMTP app password."""
    try:
        import os as _os

        from atlas.config import get_config
        from atlas.mail.client import IMAPBackend, MailClient

        cfg = get_config()
        mail = getattr(getattr(cfg, "plugins", None), "mail", None)
        host = str(getattr(mail, "host", "") or "").strip() if mail else ""
        username = str(getattr(mail, "username", "") or "").strip() if mail else ""
        password_env = (
            str(getattr(mail, "password_env", "") or "ATLAS_MAIL_PASSWORD")
            if mail
            else "ATLAS_MAIL_PASSWORD"
        )
        password = _os.environ.get(password_env, "")
        port = int(getattr(mail, "port", 993) or 993) if mail else 993
        use_ssl = bool(getattr(mail, "use_ssl", True)) if mail else True
        folder = str(getattr(mail, "default_folder", "INBOX") or "INBOX") if mail else "INBOX"
        max_results = int(getattr(mail, "max_results", 25) or 25) if mail else 25
        timeout = float(getattr(mail, "timeout", 20) or 20) if mail else 20.0

        # Fallback: same Gmail mailbox as SMTP (app password works for IMAP).
        if not host or not username or not password:
            email_cfg = cfg.email
            smtp_user = str(getattr(email_cfg, "username", "") or "").strip()
            smtp_host = str(getattr(email_cfg, "host", "") or "").strip().lower()
            smtp_pw = _os.environ.get(
                str(getattr(email_cfg, "password_env", "") or "ATLAS_SMTP_PASSWORD"),
                "",
            )
            if smtp_user and smtp_pw and "gmail" in smtp_host:
                host = "imap.gmail.com"
                username = smtp_user
                password = smtp_pw
                port = 993
                use_ssl = True
            else:
                return None

        backend = IMAPBackend(
            host=host,
            port=port,
            username=username,
            password=password,
            use_ssl=use_ssl,
            timeout=timeout,
        )
        if not backend.available():
            return None
        return MailClient(backend, default_folder=folder, max_results=max_results)
    except Exception:  # noqa: BLE001
        _log.debug("mail client build failed", exc_info=True)
        return None


def escalate_login_email(
    data_dir: str | Path | None,
    health: dict[str, Any],
    *,
    sender: Any | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Email when a Zerodha token is required.

    One mail while a reply is still outstanding. Send again when that reply
    already completed and the session died, or when Zerodha rejected the
    request_token. A once-per-day gate would stay silent after an expired token.
    """
    status = str(health.get("status") or "")
    if status not in {"LOGIN_REQUIRED", "EXPIRED"}:
        return {"sent": False, "reason": "not_login_required"}
    now = datetime.now(_IST)
    if now.hour < 6 and not force:
        return {"sent": False, "reason": "before_06_ist"}
    day = _ist_day()
    pending = load_pending(data_dir)
    if (
        not force
        and pending.get("ist_day") == day
        and pending.get("status") == "awaiting_reply"
    ):
        return {"sent": False, "reason": "already_sent_today", "pending": pending.get("status")}
    relogin = bool(
        pending.get("ist_day") == day and pending.get("status") == "completed"
    )
    exchange_rejected = bool(
        pending.get("ist_day") == day and pending.get("status") == "exchange_rejected"
    )
    if exchange_rejected and not force and _rejection_notice_is_fresh(pending):
        return {
            "sent": False,
            "reason": "rejection_notice_already_sent",
            "pending": pending.get("status"),
        }
    if (
        not force
        and not relogin
        and not exchange_rejected
        and str(health.get("login_email_sent_ist_day") or "") == day
    ):
        return {"sent": False, "reason": "already_sent_today"}

    sender = sender if sender is not None else _email_sender()
    if sender is None:
        return {"sent": False, "reason": "email_not_configured"}

    public_base = atlas_public_base_url()
    login_url = login_cta_url(force=False)
    force_url = login_cta_url(force=True)
    kite_url = resolve_kite_login_url(data_dir=data_dir)
    if exchange_rejected:
        subject = (
            f"{SUBJECT_PREFIX} {status} — request token rejected, new token required ({day})"
        )
    elif relogin:
        subject = (
            f"{SUBJECT_PREFIX} {status} — session inactive, new token required ({day})"
        )
    else:
        subject = f"{SUBJECT_PREFIX} {status} — live labs paused ({day})"
    body = build_escalate_body(
        status=status,
        trading_date=str(health.get("trading_date") or day),
        login_url=login_url,
        force_login_url=force_url,
        public_base=public_base,
        kite_login_url=kite_url,
    )
    if exchange_rejected:
        body = (
            "Atlas received a reply, but Zerodha rejected that request_token.\n"
            "Kite said it is invalid or expired. A request_token is single-use "
            "and only valid for a few minutes.\n"
            "Generate a new one and reply with that fresh token only.\n\n"
            + body
        )
    elif relogin:
        body = (
            "The Zerodha session that was active earlier today is no longer valid.\n"
            "Live labs are paused until a new request_token is exchanged.\n\n"
            + body
        )
    message_id = f"<atlas-mdph-{day}-{uuid.uuid4().hex[:12]}@atlas.local>"
    ok = False
    try:
        # Prefer header-aware send when available
        if hasattr(sender, "send_to_with_headers"):
            ok = bool(
                sender.send_to_with_headers(
                    sender._to if hasattr(sender, "_to") else [],
                    subject,
                    body,
                    headers={"Message-ID": message_id, "X-Atlas-MDPH": "zerodha-login"},
                )
            )
        else:
            ok = bool(sender.send(subject, body))
    except Exception as exc:  # noqa: BLE001
        return {"sent": False, "reason": f"{type(exc).__name__}: {exc}"}

    if not ok:
        return {"sent": False, "reason": "smtp_failed"}

    pending_doc = {
        "version": VERSION,
        "ist_day": day,
        "status": "awaiting_reply",
        "provider_status": status,
        "subject": subject,
        "message_id": message_id,
        "login_url": login_url,
        "public_base": public_base,
        "sent_at": _now_iso(),
        "last_poll_at": None,
        "poll_count": 0,
        "consumed_uids": list(pending.get("consumed_uids") or [])
        if (relogin or exchange_rejected)
        else [],
        "completed_at": None,
        "result": None,
        "last_exchange_error": pending.get("last_exchange_error")
        if exchange_rejected
        else None,
        "rejection_notice_sent_at": _now_iso() if exchange_rejected else None,
    }
    save_pending(data_dir, pending_doc)

    # Stamp health without wiping other fields — caller should merge too.
    try:
        from atlas.investment.market_data_provider_health import load_health, save_health

        h = load_health(data_dir) or dict(health)
        h["login_email_sent_ist_day"] = day
        h["login_email_message_id"] = message_id
        h["login_email_public_base"] = public_base
        save_health(data_dir, h)
    except Exception:  # noqa: BLE001
        _log.debug("stamp login_email_sent failed", exc_info=True)

    try:
        from atlas.investment.market_data_provider_health import record_mdph_event

        record_mdph_event(
            data_dir,
            "login_email_escalate",
            status=status,
            ok=True,
            public_base=public_base,
            loopback="127.0.0.1" in public_base,
        )
    except Exception:  # noqa: BLE001
        pass

    return {
        "sent": True,
        "reason": "smtp_ok",
        "message_id": message_id,
        "public_base": public_base,
        "login_url": login_url,
    }


def _rejection_notice_is_fresh(pending: dict[str, Any], *, within_s: float = 1800) -> bool:
    """One rejection mail per half hour. Further expired replies must not re-mail."""
    raw = pending.get("rejection_notice_sent_at")
    if not raw:
        return False
    try:
        prev = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if prev.tzinfo is None:
            prev = prev.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - prev).total_seconds()
        return age < within_s
    except Exception:  # noqa: BLE001
        return False


def _should_poll(pending: dict[str, Any], *, now: datetime | None = None) -> bool:
    if pending.get("status") != "awaiting_reply":
        return False
    if pending.get("ist_day") != _ist_day():
        return False
    last = pending.get("last_poll_at")
    if not last:
        return True
    try:
        prev = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
        if prev.tzinfo is None:
            prev = prev.replace(tzinfo=timezone.utc)
        age = (now or datetime.now(timezone.utc)) - prev
        return age.total_seconds() >= POLL_INTERVAL_S
    except Exception:  # noqa: BLE001
        return True


def poll_token_reply(
    data_dir: str | Path | None,
    *,
    mail_client: Any | None = None,
    feed: Any | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Poll IMAP for a reply carrying request_token; complete_login on hit."""
    pending = load_pending(data_dir)
    if not pending:
        return {"ok": False, "reason": "no_pending"}
    if pending.get("ist_day") != _ist_day():
        return {"ok": False, "reason": "stale_day"}
    if pending.get("status") == "completed":
        return {"ok": True, "reason": "already_completed", "result": pending.get("result")}
    if pending.get("status") != "awaiting_reply":
        return {"ok": False, "reason": f"status={pending.get('status')}"}

    # Browser / manual login may have already succeeded — close the wait even
    # when IMAP poll is throttled, so email activation does not keep nagging.
    try:
        from atlas.investment.zerodha_feed import ZerodhaMarketFeed

        probe_feed = feed or ZerodhaMarketFeed.from_env(data_dir=data_dir)
        if probe_feed.has_session:
            pending["status"] = "completed"
            pending["completed_at"] = _now_iso()
            pending["result"] = {"ok": True, "via": "session_already_present"}
            pending["last_poll_reason"] = "session_already_present"
            save_pending(data_dir, pending)
            return {"ok": True, "reason": "session_already_present"}
    except Exception:  # noqa: BLE001
        pass

    if not force and not _should_poll(pending):
        return {"ok": False, "reason": "poll_throttled", "poll_count": pending.get("poll_count")}

    client = mail_client if mail_client is not None else _mail_client()
    if client is None:
        pending["last_poll_at"] = _now_iso()
        pending["poll_count"] = int(pending.get("poll_count") or 0) + 1
        pending["last_poll_reason"] = "imap_unavailable"
        save_pending(data_dir, pending)
        return {"ok": False, "reason": "imap_unavailable"}

    day = _ist_day()
    # Broad search — Gmail IMAP text search for our subject tag + day.
    query = f"{SUBJECT_PREFIX} {day}"
    try:
        search = client.search(query, limit=15)
    except Exception as exc:  # noqa: BLE001
        pending["last_poll_at"] = _now_iso()
        pending["poll_count"] = int(pending.get("poll_count") or 0) + 1
        pending["last_poll_reason"] = f"search_failed:{type(exc).__name__}"
        save_pending(data_dir, pending)
        return {"ok": False, "reason": f"search_failed:{type(exc).__name__}"}

    outcome = str(search.get("outcome") or "")
    messages = list(search.get("messages") or []) if outcome in {"ok", "empty"} else []
    if outcome not in {"ok", "empty"}:
        pending["last_poll_at"] = _now_iso()
        pending["poll_count"] = int(pending.get("poll_count") or 0) + 1
        pending["last_poll_reason"] = f"search_{outcome}"
        save_pending(data_dir, pending)
        return {"ok": False, "reason": f"search_{outcome}"}

    consumed = {str(x) for x in (pending.get("consumed_uids") or []) if x}
    found_token: str | None = None
    found_uid: str | None = None
    found_is_reply = False

    # Prefer operator replies (Re:) over Atlas's own escalate notices in the same thread.
    ordered: list[dict[str, Any]] = []
    for summary in messages:
        if isinstance(summary, dict):
            ordered.append(summary)
    ordered.sort(
        key=lambda s: (
            0
            if str(s.get("subject") or "").lower().startswith("re:")
            else 1
        )
    )

    for summary in ordered:
        uid = str(summary.get("uid") or "")
        if not uid or uid in consumed:
            continue
        subj = str(summary.get("subject") or "")
        is_reply = subj.lower().lstrip().startswith("re:")
        # Prefer replies (Re:) or same subject thread
        if day not in subj and SUBJECT_PREFIX not in subj and "Re:" not in subj:
            # still open — body may carry the token without subject echo
            pass
        try:
            full = client.message(uid)
        except Exception:  # noqa: BLE001
            continue
        body = ""
        if isinstance(full, dict):
            if full.get("outcome") == "ok" and isinstance(full.get("message"), dict):
                body = str(full["message"].get("body") or "")
            else:
                body = str(full.get("body") or "")
        if not body:
            body = str(summary.get("snippet") or summary.get("body") or "")
        # Skip Atlas escalate/rejection notices — they must never be exchanged.
        if (not is_reply) and (
            "Provider status:" in body
            or "Live-required labs" in body
            or "request token rejected" in subj.lower()
            or "live labs paused" in subj.lower()
        ):
            consumed.add(uid)
            continue
        tok = parse_request_token_from_text(body)
        # Always mark read-through UIDs so instructional mail is not retried forever.
        consumed.add(uid)
        if tok:
            found_token = tok
            found_uid = uid
            found_is_reply = is_reply
            break

    pending["last_poll_at"] = _now_iso()
    pending["poll_count"] = int(pending.get("poll_count") or 0) + 1
    pending["consumed_uids"] = sorted(consumed)[-40:]

    if not found_token:
        pending["last_poll_reason"] = "no_token_in_replies"
        save_pending(data_dir, pending)
        return {
            "ok": False,
            "reason": "no_token_in_replies",
            "searched": len(messages),
            "poll_count": pending["poll_count"],
        }

    # Exchange — never log token
    try:
        from atlas.investment.zerodha_feed import ZerodhaMarketFeed

        zfeed = feed or ZerodhaMarketFeed.from_env(data_dir=data_dir)
        result = zfeed.complete_login(found_token)
    except Exception as exc:  # noqa: BLE001
        pending["last_exchange_error"] = type(exc).__name__
        pending["last_poll_reason"] = f"complete_login_failed:{type(exc).__name__}"
        # Only a failed *operator reply* may arm a rejection notice email.
        if found_is_reply and not _rejection_notice_is_fresh(pending):
            pending["status"] = "exchange_rejected"
        else:
            pending["status"] = "awaiting_reply"
        save_pending(data_dir, pending)
        _log.warning(
            "zerodha token email complete_login failed uid=%s err=%s",
            found_uid,
            type(exc).__name__,
        )
        return {"ok": False, "reason": f"complete_login_failed:{type(exc).__name__}"}

    if not result.get("ok"):
        err = str(result.get("error") or "rejected")
        pending["last_exchange_error"] = err[:180]
        pending["last_poll_reason"] = f"complete_login:{err[:180]}"
        # Keep polling. Second mail only if a real Re: reply was rejected by Kite.
        if found_is_reply and not _rejection_notice_is_fresh(pending):
            pending["status"] = "exchange_rejected"
        else:
            pending["status"] = "awaiting_reply"
        save_pending(data_dir, pending)
        _log.warning(
            "zerodha token email exchange rejected uid=%s error=%s",
            found_uid,
            result.get("error"),
        )
        return {
            "ok": False,
            "reason": "complete_login_rejected",
            "error": result.get("error"),
        }

    pending["status"] = "completed"
    pending["completed_at"] = _now_iso()
    pending["result"] = {
        "ok": True,
        "via": "email_reply",
        "uid": found_uid,
        "user_id": result.get("user_id"),
        "ist_day": result.get("ist_day"),
        "token_len": len(found_token),
    }
    pending["last_poll_reason"] = "completed"
    save_pending(data_dir, pending)

    try:
        from atlas.investment.market_data_provider_health import (
            evaluate_zerodha_health,
            record_mdph_event,
        )

        evaluate_zerodha_health(
            data_dir, feed=zfeed, probe=True, refresh_instruments=False, force_reprobe=True
        )
        record_mdph_event(
            data_dir,
            "login_email_token_accepted",
            via="email_reply",
            uid=found_uid,
            user_id=result.get("user_id"),
        )
    except Exception:  # noqa: BLE001
        _log.debug("post-login health refresh failed", exc_info=True)

    # Confirm without secrets
    try:
        sender = _email_sender()
        if sender is not None:
            sender.send(
                subject=f"{SUBJECT_PREFIX} session OK ({day})",
                body=(
                    f"Zerodha request_token from your email reply was accepted.\n"
                    f"Session IST day: {result.get('ist_day')}\n"
                    f"User: {result.get('user_id')}\n"
                    f"Live-required labs may resume on next paper tick.\n"
                ),
            )
    except Exception:  # noqa: BLE001
        pass

    _log.info(
        "zerodha token email login completed via reply uid=%s user=%s",
        found_uid,
        result.get("user_id"),
    )
    return {
        "ok": True,
        "reason": "completed",
        "via": "email_reply",
        "uid": found_uid,
        "user_id": result.get("user_id"),
    }
