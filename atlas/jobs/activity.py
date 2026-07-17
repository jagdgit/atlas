"""Job activity feed — the "watch it work" recorder (RL / D3.11 / §5a, C0).

Stage 3, Step 2. A tiny, dependency-light recorder that turns what a job is *doing*
into a stream of human-readable progress events, so a running job is observable live
in the Web Console (poll-based today; SSE later if 2s polling feels laggy).

Each event is durable (appended to the job workspace's ``activity.jsonl``) **and**
emitted on the event bus (``job.activity``). The recorder is deliberately reusable and
best-effort: the same object is handed to the research pipeline in later steps
(searching → acquiring → reading → extracting → deciding), and a logging failure must
never break the work it is describing.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from atlas.jobs.workspace import JobWorkspace

# Coarse phases so the UI can group/icon events consistently across the pipeline.
PHASE_LIFECYCLE = "lifecycle"   # job created / finalized
PHASE_PLANNING = "planning"     # async JobPlanner decompose (3.2e)
PHASE_STEP = "step"             # a job step started / finished / blocked
PHASE_SEARCH = "search"         # searching web / scholar
PHASE_CLASSIFY = "classify"     # source classification
PHASE_ACQUIRE = "acquire"       # downloading documents
PHASE_READ = "read"             # reading / extracting text
PHASE_EXTRACT = "extract"       # claim extraction
PHASE_VERIFY = "verify"         # verification / decision
PHASE_REPORT = "report"         # report generation
PHASE_LEARN = "learn"           # learning / storing


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ActivityRecorder:
    """Records job progress to the workspace + event bus (RL).

    Construct with the job's workspace (durable storage) and, optionally, the event
    bus (live push). Either may be ``None`` — the recorder still no-ops safely, which
    keeps it trivial to use in tests.
    """

    def __init__(
        self,
        job_id: str,
        *,
        workspace: "JobWorkspace | None" = None,
        events: Any = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._job_id = str(job_id)
        self._workspace = workspace
        self._events = events
        self._logger = logger or logging.getLogger("atlas.jobs.activity")

    def record(self, phase: str, message: str, **data: Any) -> dict[str, Any]:
        """Record one progress event. Never raises."""
        event = {
            "job_id": self._job_id,
            "ts": _now(),
            "phase": phase,
            "message": message,
        }
        if data:
            event["data"] = data
        if self._workspace is not None:
            try:
                self._workspace.append_activity(event)
            except Exception:  # noqa: BLE001 - activity is best-effort
                self._logger.debug("activity append failed for job %s", self._job_id)
        if self._events is not None:
            try:
                self._events.emit("job.activity", event, source="jobs")
            except Exception:  # noqa: BLE001 - notifications are best-effort
                self._logger.debug("activity emit failed for job %s", self._job_id)
        return event
