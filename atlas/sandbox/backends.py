"""Sandbox backends (D6 — hybrid).

``SandboxBackend`` is the swap point. ``SubprocessBackend`` (the default) runs code in
a child interpreter with POSIX ``rlimit`` caps (CPU, address space, file size, no core
dump), a hard wall-clock timeout that kills the whole process group, a scratch working
dir, a stripped environment, and — unless explicitly enabled — an in-interpreter
**network block**. ``DockerBackend`` is a selectable placeholder for stronger isolation
(reports itself unavailable until implemented, so gaps are honest — R2).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Protocol

from atlas.sandbox.models import (
    OUTCOME_BLOCKED,
    OUTCOME_ERROR,
    OUTCOME_OK,
    OUTCOME_TIMEOUT,
    ExecutionResult,
)

_RESERVED = {"_runner.py", "main.py", "result.json"}

# Injected before user code when network is disabled: neutralise the socket layer so
# naive net use (urllib/requests/http) fails loudly rather than reaching out. This is a
# *soft* block (same-interpreter); hard isolation is the Docker backend's job.
_NETWORK_BLOCK = """\
import socket as _s
def _no_net(*a, **k):
    raise OSError("network access is disabled in the Atlas sandbox")
_s.socket = _no_net
_s.create_connection = _no_net
"""

_RUNNER_TEMPLATE = """\
{network_block}
import runpy
runpy.run_path("main.py", run_name="__main__")
"""


class SandboxBackend(Protocol):
    name: str

    def available(self) -> tuple[bool, str]: ...

    def run(
        self,
        code: str,
        *,
        workdir: Path,
        timeout: float,
        memory_mb: int,
        cpu_seconds: int,
        max_output_bytes: int,
        files: dict[str, str] | None = None,
        stdin: str | None = None,
        network: bool = False,
    ) -> ExecutionResult: ...


def _truncate(text: str, limit: int) -> tuple[str, bool]:
    data = text or ""
    if limit and len(data) > limit:
        return data[:limit], True
    return data, False


class SubprocessBackend:
    """Run Python in a resource-limited child process (the default backend)."""

    name = "subprocess"

    def __init__(self, python_exe: str | None = None) -> None:
        self._python = python_exe or sys.executable

    def available(self) -> tuple[bool, str]:
        if not self._python or not Path(self._python).exists():
            return False, f"python interpreter not found: {self._python}"
        return True, ""

    def _limits(self, memory_mb: int, cpu_seconds: int, fsize_bytes: int):
        # Returns a preexec_fn (POSIX only) applying rlimits in the child.
        try:
            import resource
        except ImportError:  # pragma: no cover - non-POSIX
            return None

        def _apply() -> None:
            resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 1))
            if memory_mb:
                nbytes = memory_mb * 1024 * 1024
                try:
                    resource.setrlimit(resource.RLIMIT_AS, (nbytes, nbytes))
                except (ValueError, OSError):  # pragma: no cover - platform dependent
                    pass
            if fsize_bytes:
                resource.setrlimit(resource.RLIMIT_FSIZE, (fsize_bytes, fsize_bytes))
            try:
                resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
            except (ValueError, OSError):  # pragma: no cover
                pass

        return _apply

    def run(
        self,
        code: str,
        *,
        workdir: Path,
        timeout: float,
        memory_mb: int,
        cpu_seconds: int,
        max_output_bytes: int,
        files: dict[str, str] | None = None,
        stdin: str | None = None,
        network: bool = False,
    ) -> ExecutionResult:
        workdir.mkdir(parents=True, exist_ok=True)
        (workdir / "main.py").write_text(code, encoding="utf-8")
        block = "" if network else _NETWORK_BLOCK
        (workdir / "_runner.py").write_text(
            _RUNNER_TEMPLATE.format(network_block=block), encoding="utf-8"
        )
        for name, content in (files or {}).items():
            safe = Path(name).name  # never escape the workdir
            (workdir / safe).write_text(content, encoding="utf-8")

        env = {
            "PATH": "/usr/bin:/bin",
            "HOME": str(workdir),
            "TMPDIR": str(workdir),
            "LC_ALL": "C.UTF-8",
            "LANG": "C.UTF-8",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        cmd = [self._python, "-I", "-B", "_runner.py"]
        fsize = max(max_output_bytes * 4, 8 * 1024 * 1024)

        started = time.monotonic()
        try:
            proc = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
                cmd,
                cwd=str(workdir),
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
                preexec_fn=self._limits(memory_mb, cpu_seconds, fsize),
            )
        except OSError as exc:
            return ExecutionResult(
                outcome=OUTCOME_BLOCKED,
                error=f"failed to start sandbox process: {exc}",
                backend=self.name,
            )

        timed_out = False
        try:
            out, err = proc.communicate(input=stdin, timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            self._kill_group(proc)
            out, err = proc.communicate()
        duration_ms = int((time.monotonic() - started) * 1000)

        out, t1 = _truncate(out, max_output_bytes)
        err, t2 = _truncate(err, max_output_bytes)
        rc = proc.returncode

        if timed_out:
            outcome, error = OUTCOME_TIMEOUT, f"timed out after {timeout:g}s"
        elif rc == 0:
            outcome, error = OUTCOME_OK, None
        else:
            outcome = OUTCOME_ERROR
            error = (err.strip().splitlines() or [f"exited with code {rc}"])[-1]

        return ExecutionResult(
            outcome=outcome,
            stdout=out,
            stderr=err,
            returncode=rc,
            duration_ms=duration_ms,
            timed_out=timed_out,
            truncated=t1 or t2,
            error=error,
            result=self._read_result(workdir),
            artifacts=self._artifacts(workdir, files or {}),
            backend=self.name,
        )

    @staticmethod
    def _kill_group(proc: subprocess.Popen) -> None:
        import signal

        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):  # pragma: no cover
            try:
                proc.kill()
            except ProcessLookupError:
                pass

    @staticmethod
    def _read_result(workdir: Path):
        rp = workdir / "result.json"
        if not rp.is_file():
            return None
        try:
            return json.loads(rp.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return None

    @staticmethod
    def _artifacts(workdir: Path, inputs: dict[str, str]) -> dict[str, int]:
        reserved = _RESERVED | {Path(n).name for n in inputs}
        out: dict[str, int] = {}
        for p in sorted(workdir.iterdir()):
            if p.is_file() and p.name not in reserved:
                out[p.name] = p.stat().st_size
        return out


class DockerBackend:
    """Placeholder for Docker-per-execution isolation (D6, swappable later).

    Selectable via config so the design is ready, but honestly reports itself
    unavailable until implemented — every run returns a ``blocked`` outcome (R2).
    """

    name = "docker"

    def available(self) -> tuple[bool, str]:
        return False, "docker sandbox backend is not implemented yet"

    def run(self, code: str, **kwargs) -> ExecutionResult:
        return ExecutionResult(
            outcome=OUTCOME_BLOCKED,
            error="docker sandbox backend is not implemented yet",
            backend=self.name,
        )


def create_backend(name: str, *, python_exe: str | None = None) -> SandboxBackend:
    name = (name or "subprocess").lower()
    if name == "subprocess":
        return SubprocessBackend(python_exe=python_exe)
    if name == "docker":
        return DockerBackend()
    raise ValueError(f"unknown sandbox backend: {name!r}")
