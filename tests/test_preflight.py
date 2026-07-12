"""Tests for preflight checks (S22) — pure config validation, no external deps."""

from __future__ import annotations

from atlas.config import get_config
from atlas.kernel.preflight import (
    CHECK_FAIL,
    CHECK_OK,
    CHECK_WARN,
    check_config,
    worst_status,
)


def _cfg():
    return get_config().model_copy(deep=True)


def _by_name(checks):
    return {c.name: c for c in checks}


def test_config_checks_pass_on_defaults(tmp_path):
    cfg = _cfg()
    cfg.api.keys = ["k"]
    for name in ("data", "documents", "logs", "backups"):
        setattr(cfg.paths, name, tmp_path / name)
    checks = check_config(cfg)
    names = _by_name(checks)
    assert names["api.keys"].status == CHECK_OK
    assert names["paths.data"].status == CHECK_OK
    assert names["sandbox.backend"].status == CHECK_OK


def test_missing_api_keys_warns():
    cfg = _cfg()
    cfg.api.keys = []
    checks = _by_name(check_config(cfg))
    assert checks["api.keys"].status == CHECK_WARN


def test_underprovisioned_workers_warns():
    cfg = _cfg()
    cfg.scheduler.workers = 1
    cfg.jobs.max_concurrent = 5
    checks = _by_name(check_config(cfg))
    assert checks["scheduler.workers"].status == CHECK_WARN


def test_bad_sandbox_backend_fails():
    cfg = _cfg()
    cfg.sandbox.backend = "vm"
    checks = _by_name(check_config(cfg))
    assert checks["sandbox.backend"].status == CHECK_FAIL
    assert worst_status(check_config(cfg)) == CHECK_FAIL


def test_worst_status_folds():
    from atlas.kernel.preflight import Check

    assert worst_status([]) == CHECK_OK
    assert worst_status([Check("a", CHECK_OK, ""), Check("b", CHECK_WARN, "")]) == CHECK_WARN
    assert worst_status(
        [Check("a", CHECK_WARN, ""), Check("b", CHECK_FAIL, "")]
    ) == CHECK_FAIL
