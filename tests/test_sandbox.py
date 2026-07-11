"""Python execution sandbox tests (Sprint 16, D6).

These run *real* child interpreters (hermetic: fixed argv, tmp working dirs, no
network) to prove isolation actually works — outcomes, timeout kill, the network
block, result.json capture, artifacts, and honest 'blocked' states.
"""

from __future__ import annotations

import pytest

from atlas.sandbox.backends import DockerBackend, SubprocessBackend, create_backend
from atlas.sandbox.models import (
    OUTCOME_BLOCKED,
    OUTCOME_ERROR,
    OUTCOME_OK,
    OUTCOME_TIMEOUT,
)
from atlas.sandbox.service import PythonSandboxService


def _backend_run(backend, code, workdir, **kw):
    params = dict(
        workdir=workdir,
        timeout=10.0,
        memory_mb=0,  # skip RLIMIT_AS to avoid platform-dependent startup flakiness
        cpu_seconds=10,
        max_output_bytes=65_536,
    )
    params.update(kw)
    return backend.run(code, **params)


# --- SubprocessBackend ----------------------------------------------------
def test_ok_run_captures_stdout(tmp_path):
    res = _backend_run(SubprocessBackend(), "print('hello atlas')", tmp_path / "r")
    assert res.outcome == OUTCOME_OK
    assert res.ok
    assert "hello atlas" in res.stdout
    assert res.returncode == 0


def test_error_run_reports_nonzero(tmp_path):
    res = _backend_run(SubprocessBackend(), "raise ValueError('boom')", tmp_path / "r")
    assert res.outcome == OUTCOME_ERROR
    assert res.returncode != 0
    assert "ValueError" in res.stderr


def test_timeout_is_killed(tmp_path):
    res = _backend_run(
        SubprocessBackend(), "import time; time.sleep(30)", tmp_path / "r", timeout=1.0
    )
    assert res.outcome == OUTCOME_TIMEOUT
    assert res.timed_out


def test_network_blocked_by_default(tmp_path):
    code = "import socket; socket.socket()"
    res = _backend_run(SubprocessBackend(), code, tmp_path / "r")
    assert res.outcome == OUTCOME_ERROR
    assert "network access is disabled" in res.stderr


def test_network_allowed_when_enabled(tmp_path):
    # With network on, constructing a socket must not be blocked (no actual I/O).
    code = "import socket; s = socket.socket(); s.close(); print('ok')"
    res = _backend_run(SubprocessBackend(), code, tmp_path / "r", network=True)
    assert res.outcome == OUTCOME_OK
    assert "ok" in res.stdout


def test_result_json_is_parsed(tmp_path):
    code = "import json; json.dump({'value': 42}, open('result.json', 'w'))"
    res = _backend_run(SubprocessBackend(), code, tmp_path / "r")
    assert res.outcome == OUTCOME_OK
    assert res.result == {"value": 42}


def test_artifacts_are_listed(tmp_path):
    code = "open('out.txt', 'w').write('data')"
    res = _backend_run(SubprocessBackend(), code, tmp_path / "r")
    assert "out.txt" in res.artifacts
    assert res.artifacts["out.txt"] == 4


def test_input_files_are_available_not_artifacts(tmp_path):
    code = "print(open('data.txt').read())"
    res = _backend_run(
        SubprocessBackend(), code, tmp_path / "r", files={"data.txt": "seed"}
    )
    assert res.outcome == OUTCOME_OK
    assert "seed" in res.stdout
    assert "data.txt" not in res.artifacts


def test_output_truncation(tmp_path):
    code = "print('x' * 10000)"
    res = _backend_run(
        SubprocessBackend(), code, tmp_path / "r", max_output_bytes=100
    )
    assert res.truncated
    assert len(res.stdout) <= 100


# --- DockerBackend + factory ---------------------------------------------
def test_docker_backend_reports_unavailable():
    ok, reason = DockerBackend().available()
    assert not ok and "not implemented" in reason


def test_docker_backend_run_is_blocked():
    res = DockerBackend().run("print(1)")
    assert res.outcome == OUTCOME_BLOCKED


def test_create_backend_dispatch():
    assert isinstance(create_backend("subprocess"), SubprocessBackend)
    assert isinstance(create_backend("docker"), DockerBackend)
    with pytest.raises(ValueError):
        create_backend("nope")


# --- PythonSandboxService -------------------------------------------------
def test_service_run_ok(tmp_path):
    svc = PythonSandboxService(workdir=tmp_path, memory_mb=0, cpu_seconds=10)
    out = svc.run("print('hi')")
    assert out["outcome"] == OUTCOME_OK
    assert "hi" in out["stdout"]
    assert out["workdir"].startswith(str(tmp_path))


def test_service_rejects_empty_code(tmp_path):
    svc = PythonSandboxService(workdir=tmp_path)
    out = svc.run("   ")
    assert out["outcome"] == OUTCOME_BLOCKED


def test_service_rejects_oversize_code(tmp_path):
    svc = PythonSandboxService(workdir=tmp_path, max_code_bytes=10)
    out = svc.run("print('a very long program')")
    assert out["outcome"] == OUTCOME_BLOCKED
    assert "max_code_bytes" in out["error"]


def test_service_run_file(tmp_path):
    script = tmp_path / "prog.py"
    script.write_text("print('from file')", encoding="utf-8")
    svc = PythonSandboxService(workdir=tmp_path / "work", memory_mb=0, cpu_seconds=10)
    out = svc.run_file(str(script))
    assert out["outcome"] == OUTCOME_OK
    assert "from file" in out["stdout"]


def test_service_run_missing_file(tmp_path):
    svc = PythonSandboxService(workdir=tmp_path)
    out = svc.run_file(str(tmp_path / "ghost.py"))
    assert out["outcome"] == OUTCOME_BLOCKED


def test_service_blocked_when_backend_unavailable(tmp_path):
    svc = PythonSandboxService(DockerBackend(), workdir=tmp_path)
    out = svc.run("print('x')")
    assert out["outcome"] == OUTCOME_BLOCKED


def test_service_health_check(tmp_path):
    svc = PythonSandboxService(workdir=tmp_path)
    status = svc.health_check()
    assert status.healthy
    assert status.data["backend"] == "subprocess"
