"""PythonSandboxService — the ``python`` capability (S16).

Owns the sandbox policy (limits, network default, working-dir root) and delegates the
actual run to a ``SandboxBackend`` (subprocess by default; Docker swappable via config).
Every entry point returns a serialisable ``ExecutionResult`` dict — a run never raises
into the caller, so a job degrades honestly (R2/R3).
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any

from atlas.sandbox.backends import SandboxBackend, SubprocessBackend
from atlas.sandbox.models import OUTCOME_BLOCKED, ExecutionResult
from atlas.services.base import HealthStatus


class PythonSandboxService:
    name = "python"

    def __init__(
        self,
        backend: SandboxBackend | None = None,
        *,
        workdir: str | Path,
        timeout: float = 30.0,
        memory_mb: int = 1024,
        cpu_seconds: int = 30,
        max_output_bytes: int = 262_144,
        max_code_bytes: int = 262_144,
        network: bool = False,
        logger: logging.Logger | None = None,
    ) -> None:
        self._backend = backend or SubprocessBackend()
        self._root = Path(workdir)
        self._timeout = timeout
        self._memory_mb = memory_mb
        self._cpu_seconds = cpu_seconds
        self._max_output_bytes = max_output_bytes
        self._max_code_bytes = max_code_bytes
        self._network = network
        self._logger = logger or logging.getLogger("atlas.sandbox")

    # --- capability API -------------------------------------------------
    def run(
        self,
        code: str,
        *,
        timeout: float | None = None,
        files: dict[str, str] | None = None,
        stdin: str | None = None,
        network: bool | None = None,
    ) -> dict[str, Any]:
        code = code or ""
        if not code.strip():
            return ExecutionResult(
                outcome=OUTCOME_BLOCKED, error="no code provided",
                backend=self._backend.name,
            ).as_dict()
        if len(code.encode("utf-8")) > self._max_code_bytes:
            return ExecutionResult(
                outcome=OUTCOME_BLOCKED,
                error=f"code exceeds max_code_bytes ({self._max_code_bytes})",
                backend=self._backend.name,
            ).as_dict()

        ok, reason = self._backend.available()
        if not ok:
            return ExecutionResult(
                outcome=OUTCOME_BLOCKED, error=reason, backend=self._backend.name
            ).as_dict()

        run_dir = self._root / uuid.uuid4().hex
        try:
            result = self._backend.run(
                code,
                workdir=run_dir,
                timeout=timeout if timeout is not None else self._timeout,
                memory_mb=self._memory_mb,
                cpu_seconds=self._cpu_seconds,
                max_output_bytes=self._max_output_bytes,
                files=files,
                stdin=stdin,
                network=self._network if network is None else network,
            )
        except Exception as exc:  # noqa: BLE001 - a backend must never crash the caller
            self._logger.exception("sandbox run failed")
            return ExecutionResult(
                outcome=OUTCOME_BLOCKED,
                error=f"sandbox error: {exc}",
                backend=self._backend.name,
            ).as_dict()

        payload = result.as_dict()
        payload["workdir"] = str(run_dir)
        return payload

    def run_file(self, path: str, **kwargs: Any) -> dict[str, Any]:
        p = Path(path).expanduser()
        if not p.is_file():
            return ExecutionResult(
                outcome=OUTCOME_BLOCKED, error=f"file not found: {p}",
                backend=self._backend.name,
            ).as_dict()
        return self.run(p.read_text(encoding="utf-8"), **kwargs)

    # --- lifecycle ------------------------------------------------------
    def start(self) -> None:
        self._root.mkdir(parents=True, exist_ok=True)

    def stop(self) -> None:
        return None

    def health_check(self) -> HealthStatus:
        ok, reason = self._backend.available()
        return HealthStatus(
            healthy=ok,
            detail=(
                f"sandbox ready ({self._backend.name}, network="
                f"{'on' if self._network else 'off'})"
                if ok
                else f"sandbox unavailable: {reason}"
            ),
            data={"backend": self._backend.name, "network": self._network},
        )
