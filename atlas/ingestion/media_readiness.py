"""Capability readiness for ``media.learn`` (Acquisition Closure · CR.1)."""

from __future__ import annotations

from typing import Any


def build_media_readiness(
    *,
    browser: str = "unavailable",
    dom_captions: str = "ready",
    official_captions: str = "not_configured",
    media_obtain: str = "not_configured",
    speech_to_text: str = "missing",
    operator_upload: str = "ready",
) -> dict[str, Any]:
    """Return a readiness matrix + short assessment for journal/report."""
    caps = {
        "browser": browser,
        "dom_captions": dom_captions,
        "official_captions": official_captions,
        "media_obtain": media_obtain,
        "speech_to_text": speech_to_text,
        "operator_upload": operator_upload,
    }
    auto_viable = False
    # Viable automatic spoken-content paths under current config.
    if official_captions == "ready":
        auto_viable = True
    if browser in ("ready",) and dom_captions == "ready":
        # Browser may yield captions or at least metadata Asset (BA.1b).
        auto_viable = True
    if media_obtain == "ready" and speech_to_text == "ready":
        auto_viable = True

    if auto_viable:
        assessment = (
            "At least one automatic acquisition path is configured; "
            "strategies marked ready will run."
        )
    else:
        assessment = (
            "No fully reliable automatic spoken-content path under current config "
            "(official captions not configured and/or media obtain + speech_to_text "
            "not ready). Operator upload remains available."
        )
        # Browser alone can still produce metadata Assets — note that.
        if browser == "ready":
            assessment += (
                " Browser is ready and will still attempt DOM captions / metadata Asset."
            )
        if media_obtain == "missing":
            assessment += " Media obtain is enabled but yt-dlp is missing from PATH."
        elif media_obtain == "not_configured":
            assessment += (
                " Enable plugins.youtube.media_obtain_enabled (+ yt-dlp) for caption-less"
                " media bytes."
            )

    return {
        "capabilities": caps,
        "automatic_path_viable": auto_viable,
        "assessment": assessment,
    }


def format_readiness_block(readiness: dict[str, Any] | None) -> str:
    if not readiness:
        return ""
    caps = readiness.get("capabilities") or {}
    lines = ["Capability readiness", ""]
    for key in (
        "browser",
        "dom_captions",
        "official_captions",
        "media_obtain",
        "speech_to_text",
        "operator_upload",
    ):
        if key in caps:
            label = key.replace("_", " ")
            lines.append(f"  {label:<22} {caps[key]}")
    lines.append("")
    lines.append(f"Assessment: {readiness.get('assessment') or ''}")
    return "\n".join(lines)
