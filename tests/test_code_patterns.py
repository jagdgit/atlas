"""Tests for pattern mining (S14, §5b.1 layer 6)."""

from __future__ import annotations

from atlas.code.parser import CodeParser
from atlas.code.patterns import mine_patterns
from atlas.code.repomap import build_repo_map, read_manifests

_SRC = '''\
import uuid
from dataclasses import dataclass


class UserRepository:
    pass


class OrderRepository:
    pass


class BillingService:
    pass


class AuthService:
    pass
'''


def _mine(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname="d"\ndependencies=["pytest","psycopg"]\n', encoding="utf-8"
    )
    (tmp_path / "Dockerfile").write_text("FROM python\n", encoding="utf-8")
    f = tmp_path / "app.py"
    f.write_text(_SRC, encoding="utf-8")
    parser = CodeParser()
    parses = [parser.parse_text(_SRC, "app.py")]
    repo_map = build_repo_map(tmp_path, parses, read_manifests(tmp_path))
    return {p.name: p for p in mine_patterns(repo_map, parses)}


def test_detects_repository_and_service_patterns(tmp_path):
    pats = _mine(tmp_path)
    assert "Repository pattern" in pats
    assert "Service layer" in pats
    assert pats["Repository pattern"].confidence > 0.5
    assert pats["Repository pattern"].evidence


def test_detects_manifest_signals(tmp_path):
    pats = _mine(tmp_path)
    assert "pytest testing" in pats
    assert "PostgreSQL" in pats
    assert "Docker" in pats


def test_detects_import_signals(tmp_path):
    pats = _mine(tmp_path)
    assert "UUID identifiers" in pats
    assert "Dataclasses" in pats


def test_patterns_sorted_by_confidence(tmp_path):
    pats = list(_mine(tmp_path).values())
    confidences = [p.confidence for p in pats]
    assert confidences == sorted(confidences, reverse=True)


def test_no_false_positives_on_empty_repo(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    parser = CodeParser()
    parses = [parser.parse_text("x = 1\n", "a.py")]
    repo_map = build_repo_map(tmp_path, parses, read_manifests(tmp_path))
    assert mine_patterns(repo_map, parses) == []
