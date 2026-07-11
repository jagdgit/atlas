"""Tests for the repo map (S14): manifests → deps/frameworks/entry points."""

from __future__ import annotations

from pathlib import Path

from atlas.code.parser import CodeParser
from atlas.code.repomap import build_repo_map, iter_source_files, read_manifests


def _repo(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\n'
        'dependencies = ["fastapi>=0.1", "psycopg[binary]>=3", "pytest>=8"]\n'
        '[project.scripts]\ndemo = "demo.cli:main"\n',
        encoding="utf-8",
    )
    (tmp_path / "Dockerfile").write_text("FROM python:3.12\n", encoding="utf-8")
    (tmp_path / "manage.py").write_text("print('django')\n", encoding="utf-8")
    pkg = tmp_path / "demo"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "app.py").write_text("def main():\n    return 1\n", encoding="utf-8")
    node_modules = tmp_path / "node_modules" / "junk"
    node_modules.mkdir(parents=True)
    (node_modules / "ignored.py").write_text("x = 1\n", encoding="utf-8")
    return tmp_path


def _build(root: Path):
    parser = CodeParser()
    parses = [
        parser.parse_text(p.read_text(), p.relative_to(root).as_posix())
        for p in iter_source_files(root)
    ]
    return build_repo_map(root, parses, read_manifests(root))


def test_ignores_vendored_dirs(tmp_path):
    root = _repo(tmp_path)
    files = {p.name for p in iter_source_files(root)}
    assert "app.py" in files
    assert "ignored.py" not in files  # node_modules skipped


def test_dependencies_and_frameworks(tmp_path):
    m = _build(_repo(tmp_path))
    assert "fastapi" in m.dependencies["python"]
    assert "psycopg" in m.dependencies["python"]
    assert "FastAPI" in m.frameworks
    assert "PostgreSQL" in m.frameworks
    assert "pytest" in m.frameworks
    assert "Docker" in m.frameworks
    assert "Django" in m.frameworks  # inferred from manage.py


def test_entry_points_and_languages(tmp_path):
    m = _build(_repo(tmp_path))
    assert "manage.py" in m.entry_points
    assert "demo.cli:main" in m.entry_points
    assert m.languages.get("python", 0) >= 2
    assert m.file_count >= 2


def test_requirements_txt_deps(tmp_path):
    (tmp_path / "requirements.txt").write_text(
        "# comment\nrequests==2.31.0\nnumpy\n-e .\n", encoding="utf-8"
    )
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    m = _build(tmp_path)
    assert "requests" in m.dependencies["python"]
    assert "numpy" in m.dependencies["python"]
